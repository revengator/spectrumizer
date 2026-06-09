"""PT3 note encoding + channel packer.

Distilled from a hand-written PT3 composer whose output is verified against
Sergey Bulba's PT3 player (Vortex Tracker II). Do not "improve" the packer
without re-checking a generated .pt3 in that player — the byte format is
load-bearing.

Channel-length invariant (proven from the PT3 player source):
  * Channel A's 0x00 terminator ends the pattern; the player then resets ALL
    three channel pointers. So every channel of a pattern MUST encode EXACTLY
    the same number of rows, or B/C slip / hit their 0x00 mid-decode.
  * `encode_channel` DROPS leading rests (it fast-forwards to the first event),
    so row 0 of every channel must be a real event (a note or OFF), never REST.
  Callers (see arrange/) enforce both by padding to ROWS_PER_PATTERN and
  anchoring row 0 with OFF when empty.
"""

from __future__ import annotations

# Note encoding: PT3 maps semitones to bytes 0x50 (C-1) .. 0xAF (B-8).
NOTE_NAMES = ['C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-']
NOTE_TO_BYTE: dict[str, int] = {}
for _octave in range(1, 9):
    for _i, _name in enumerate(NOTE_NAMES):
        NOTE_TO_BYTE[f"{_name}{_octave}"] = 0x50 + (_octave - 1) * 12 + _i

PT3_NOTE_MIN = 0x50            # C-1
PT3_NOTE_MAX = 0xAF            # B-8

REST = '---'
OFF = 'OFF'


def midi_to_pt3_byte(midi_note: int, transpose: int = 0,
                     fold: bool = True) -> int:
    """MIDI note number -> PT3 note byte.

    MIDI octave o (note = 12*(o+1)+s, so middle C / MIDI 60 = C4) maps to the
    PT3 note of the same octave number (C4 -> "C-4" = 0x74), a comfortable AY
    mid-range. The real pitch depends on the AY frequency table, so tune by ear
    with `transpose`. Out-of-range notes are folded by octaves (fold=True) or
    clamped (fold=False)."""
    idx = (midi_note - 24) + transpose          # 0 == PT3 "C-1"
    if fold:
        while idx < 0:
            idx += 12
        while idx > 95:
            idx -= 12
    else:
        idx = max(0, min(95, idx))
    return 0x50 + idx


def _note_byte(note) -> int:
    """A cell's note may be a PT3 name ('C-4'), or an already-resolved byte."""
    if isinstance(note, str):
        return NOTE_TO_BYTE[note]
    return int(note)


def encode_channel(rows: list, default_sample: int = 1,
                   default_volume: int = 15, ornament: int = 0) -> bytes:
    """Pack one channel of one pattern into PT3 bytes.

    `rows` is a list of cells, one per row: REST (hold/empty), OFF (note cut),
    a note (PT3 name str or byte int), or a (note, opts) tuple where opts may
    carry 'vol', 'ornament', 'sample', 'env'. 'env' is (shape 1..14, period) to
    drive the row's note from the AY hardware envelope (buzzer bass), or 'off'
    to stop using it. Trailing rests after an event extend its NtSkip; leading
    rests are dropped (anchor row 0, see module docstring)."""
    out = bytearray()
    cur_sample = default_sample
    cur_volume = default_volume
    cur_ornament = ornament
    cur_skip = 0
    first_note_emitted = False
    initial_volume_emitted = False

    i = 0
    while i < len(rows) and rows[i] == REST:
        i += 1

    while i < len(rows):
        row = rows[i]
        note = row
        opts = {}
        if isinstance(row, tuple):
            note, opts = row[0], row[1] if len(row) > 1 else {}

        rest_after = 0
        j = i + 1
        while j < len(rows) and rows[j] == REST:
            rest_after += 1
            j += 1
        desired_skip = 1 + rest_after

        if 'vol' in opts and opts['vol'] != cur_volume:
            cur_volume = opts['vol']
            out.append(0xC0 | (cur_volume & 0x0F))
            initial_volume_emitted = True
        if 'ornament' in opts and opts['ornament'] != cur_ornament:
            cur_ornament = opts['ornament']
            out.append(0x40 | (cur_ornament & 0x0F))
        if 'sample' in opts and opts['sample'] != cur_sample:
            cur_sample = opts['sample']
            out.append(0xD0 | (cur_sample & 0x1F))
        if 'env' in opts:
            env = opts['env']
            if env == 'off' or env is None:
                out.append(0xB0)                       # envelope OFF
            else:
                shape, period = env
                if not 1 <= shape <= 14:
                    raise ValueError(
                        f"PT3 envelope shape must be 1..14 (got {shape}): shape 0 "
                        "collides with NtSkip (0xB1) and 15 with OFF (0xC0).")
                out.append(0xB1 + shape)               # set shape -> R13
                out.append((period >> 8) & 0xFF)       # period high byte
                out.append(period & 0xFF)              # period low byte

        if not initial_volume_emitted:
            out.append(0xC0 | (default_volume & 0x0F))
            initial_volume_emitted = True

        if desired_skip != cur_skip:
            cur_skip = desired_skip
            out.append(0xB1)
            out.append(desired_skip)

        if note == OFF:
            out.append(0xC0)
        else:
            if not first_note_emitted:
                out.append(0xF0 | (cur_ornament & 0x0F))
                out.append((cur_sample & 0x1F) * 2)
                first_note_emitted = True
            out.append(_note_byte(note))

        i = j

    out.append(0x00)
    return bytes(out)


def decode_row_count(data: bytes) -> int:
    """Sum the rows a packed channel occupies (for validating the per-pattern
    row invariant). Parses exactly the token grammar `encode_channel` emits."""
    rows = 0
    cur_skip = 1
    i = 0
    while i < len(data):
        b = data[i]; i += 1
        if b == 0x00:                       # end of channel
            break
        if 0xF0 <= b <= 0xFF:               # first-note preamble: + sample byte
            i += 1                          # the note byte follows next loop
            continue
        if 0xD0 <= b <= 0xEF:               # sample change
            continue
        if 0x40 <= b <= 0x4F:               # ornament change
            continue
        if b == 0xB0:                       # envelope OFF — no operand
            continue
        if b == 0xB1:                       # NtSkip change
            cur_skip = data[i]; i += 1
            continue
        if 0xB2 <= b <= 0xBF:               # set envelope — 2 period bytes follow
            i += 2
            continue
        if 0xC1 <= b <= 0xCF:               # volume change
            continue
        if b == 0xC0:                       # OFF (note cut) — a row event
            rows += cur_skip
            continue
        if 0x50 <= b <= 0xAF:               # note — a row event
            rows += cur_skip
            continue
        # any other token: ignore (no time cost)
    return rows
