"""PT3 playback — read a spectrumizer-generated module back into musical events.

This is the inverse of `pt3.encode` / `pt3.writer`: it parses the small PT3
subset this package emits (notes, OFF, sample / ornament / volume changes,
NtSkip) and yields, frame by frame (50 Hz), the per-channel state needed to
drive an AY synthesiser (see `spectrumizer.audio`).

It is **not** a full Vortex Tracker player — it understands exactly the tokens
`encode_channel` writes plus the AY hardware-envelope tokens (so buzzer-bass
modules can be auditioned), and nothing else (no pattern-command glissando /
vibrato / noise-period; sample-level tone offsets — the vibrato samples — ARE
honoured). That is enough to audition anything spectrumizer makes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FRAME_HZ = 50


@dataclass
class ParsedSample:
    """A PT3 instrument as per-tick timbre + loop point.

    Each tick is (tone_on, noise_on, amp, noise_path, noise_add, persist,
    tone_add, tone_acc): the mixer gates, the amplitude, the noise-period
    contribution — a tick on the noise path (byte1 bit7 == 0) drives the AY
    noise register by ``byte0 >> 1`` (+ a persisted slide if byte1 bit5 is
    set) — and the tone offset: a signed period delta (bytes 2-3) added to
    the note's tone period while the tick plays (vibrato/detune); with
    `tone_acc` (byte1 bit6) it also accumulates across ticks (CHP.TnAcc).
    """
    loop: int
    ticks: list  # list[tuple[bool, bool, int, bool, int, bool, int, bool]]

    def at(self, pos: int):
        return self.ticks[pos] if pos < len(self.ticks) else self.ticks[-1]

    def advance(self, pos: int) -> int:
        pos += 1
        return pos if pos < len(self.ticks) else self.loop


@dataclass
class ParsedOrnament:
    """A PT3 ornament as signed semitone offsets + loop point."""
    loop: int
    offsets: list  # list[int]

    def at(self, pos: int) -> int:
        return self.offsets[pos] if pos < len(self.offsets) else self.offsets[-1]

    def advance(self, pos: int) -> int:
        pos += 1
        return pos if pos < len(self.offsets) else self.loop


@dataclass
class RowEvent:
    """An onset on one row: a note (or a note-cut) plus the active timbre."""
    note: int | None     # PT3 note byte (0x50..0xAF), or None for OFF (note cut)
    sample: int
    ornament: int
    vol: int
    env: tuple | None = None   # (shape 1..14, period 0..65535) or None (env off)
    env_retrig: bool = False   # this event (re)wrote R13 -> the AY retriggers


@dataclass
class Module:
    speed: int
    loop_pos: int
    order: list             # pattern indices, in play order
    patterns: list          # per pattern: (chA, chB, chC), each list[RowEvent|None]
    samples: dict           # slot -> ParsedSample
    ornaments: dict         # slot -> ParsedOrnament
    name: str = ""
    author: str = ""
    tone_table: int = 1     # header 0x63; the audition synth renders table 1
    unknown_tokens: frozenset = frozenset()  # tokens outside the decoded subset


# --- the default timbres, parsed once so a header with addr 0 still plays ---
_DEFAULT_SAMPLE_FALLBACK = ParsedSample(0, [(True, False, 12, False, 0, False,
                                             0, False)])
_DEFAULT_ORNAMENT_FALLBACK = ParsedOrnament(0, [0])


def _u16(data: bytes, off: int) -> int:
    return data[off] | (data[off + 1] << 8)


def _mixer(b1: int) -> tuple[bool, bool]:
    """Decode a sample tick's byte1 mixer bits into (tone_on, noise_on).

    The real player's mixer is negative logic (CHREGS: ``RRA / AND #48``):
    byte1 bit4 disables the tone, bit7 disables the noise. So 0x80 -> tone only,
    0x10 -> noise only, 0x00 -> both, 0x90 -> neither (the buzzer mix: the
    channel is then heard only through the hardware envelope).
    """
    return not (b1 & 0x10), not (b1 & 0x80)


def parse_sample(data: bytes, addr: int) -> ParsedSample:
    """Parse one sample. Bounds-clamped: a foreign/corrupt module whose data
    runs past EOF yields the ticks that fit (never an IndexError)."""
    if addr + 2 > len(data):
        return _DEFAULT_SAMPLE_FALLBACK
    loop = data[addr]
    length = data[addr + 1] + 1
    ticks = []
    p = addr + 2
    for _ in range(length):
        if p + 4 > len(data):
            break
        b0, b1 = data[p], data[p + 1]
        tone_on, noise_on = _mixer(b1)
        noise_path = (b1 & 0x80) == 0     # bit7=0 -> this tick drives the noise period
        noise_add = (b0 >> 1) & 0xFF      # byte0 -> AddToNs contribution
        persist = (b1 & 0x20) != 0        # bit5 -> persist the noise slide (CrNsSl)
        tone_add = _u16(data, p + 2)      # bytes 2-3: signed tone-period delta
        if tone_add >= 0x8000:
            tone_add -= 0x10000
        tone_acc = (b1 & 0x40) != 0       # bit6 -> accumulate it (CHP.TnAcc)
        ticks.append((tone_on, noise_on, b1 & 0x0F, noise_path, noise_add, persist,
                      tone_add, tone_acc))
        p += 4
    if not ticks:
        return _DEFAULT_SAMPLE_FALLBACK
    return ParsedSample(min(loop, len(ticks) - 1), ticks)


def parse_ornament(data: bytes, addr: int) -> ParsedOrnament:
    """Parse one ornament. Bounds-clamped like `parse_sample`."""
    if addr + 2 > len(data):
        return _DEFAULT_ORNAMENT_FALLBACK
    loop = data[addr]
    length = data[addr + 1] + 1
    offs = []
    p = addr + 2
    for _ in range(length):
        if p >= len(data):
            break
        v = data[p]
        offs.append(v - 256 if v >= 128 else v)   # signed semitone offset
        p += 1
    if not offs:
        return _DEFAULT_ORNAMENT_FALLBACK
    return ParsedOrnament(min(loop, len(offs) - 1), offs)


def decode_channel(data: bytes, addr: int, unknown: set | None = None) -> list:
    """Decode one packed channel into a per-row list of RowEvent | None.

    Mirrors the token grammar emitted by `encode_channel`. A note/OFF event
    occupies `cur_skip` rows; the extra rows are None (held / silent).
    Tokens outside that grammar (full Vortex modules: glissando, portamento,
    PD_NOIS…) are skipped and reported into `unknown` — their operand bytes
    are NOT consumed, so decoding such a module may also desync.
    """
    rows: list = []
    cur_sample, cur_orn, cur_vol, cur_skip = 1, 0, 15, 1
    cur_env = None                          # (shape, period) or None (env off)
    cur_env_retrig = False                  # set when an env token (re)wrote R13
    i = addr
    n = len(data)
    while i < n:
        b = data[i]; i += 1
        if b == 0x00:                       # end of channel
            break
        if 0xF0 <= b <= 0xFF:               # first-note preamble (orn + sample*2)
            cur_orn = b & 0x0F
            if i >= n:                      # truncated operand (foreign module)
                break
            cur_sample = data[i] // 2; i += 1
            continue
        if 0xD0 <= b <= 0xEF:               # sample change (token = 0xD0 + slot;
            cur_sample = b - 0xD0           # NOT b & 0x1F — 0xD0 has bit4 set)
            continue
        if 0x40 <= b <= 0x4F:               # ornament change
            cur_orn = b & 0x0F
            continue
        if b == 0xB0:                       # envelope OFF
            cur_env, cur_env_retrig = None, True
            continue
        if b == 0xB1:                       # NtSkip change
            if i >= n:                      # truncated operand (foreign module)
                break
            cur_skip = data[i]; i += 1
            continue
        if 0xB2 <= b <= 0xBF:               # set envelope: shape + period (hi, lo)
            shape = b - 0xB1                # 1..14 (0xB0 is OFF, 0xB1 is NtSkip)
            if i + 1 >= n:                  # truncated operand (foreign module)
                break
            period = (data[i] << 8) | data[i + 1]; i += 2
            cur_env, cur_env_retrig = (shape, period), True
            continue
        if 0xC1 <= b <= 0xCF:               # volume change
            cur_vol = b & 0x0F
            continue
        if b == 0xC0:                       # OFF (note cut)
            rows.append(RowEvent(None, cur_sample, cur_orn, cur_vol,
                                 cur_env, cur_env_retrig))
            rows.extend([None] * (cur_skip - 1))
            cur_env_retrig = False
            continue
        if 0x50 <= b <= 0xAF:               # note
            rows.append(RowEvent(b, cur_sample, cur_orn, cur_vol,
                                 cur_env, cur_env_retrig))
            rows.extend([None] * (cur_skip - 1))
            cur_env_retrig = False
            continue
        # any other token: ignore (no time cost), but report it
        if unknown is not None:
            unknown.add(b)
    return rows


def parse_module(data: bytes) -> Module:
    """Parse a spectrumizer-generated PT3 module into a playable `Module`.

    Vortex Tracker saves the same fixed-offset header under its own 30-byte
    banner (the real player never reads the text), so both signatures are
    accepted; foreign content is then reported via `unknown_tokens`.
    """
    if len(data) < 0xC9 or not (data[:13] == b'ProTracker 3.'
                                or data[:17] == b'Vortex Tracker II'):
        raise ValueError("not a ProTracker 3 / Vortex Tracker module")
    tone_table = data[0x63]
    speed = data[0x64] or 6
    loop_pos = data[0x66]
    ppt_off = _u16(data, 0x67)

    samples = {}
    for slot in range(32):
        a = _u16(data, 0x69 + slot * 2)
        if a:
            samples[slot] = parse_sample(data, a)
    ornaments = {}
    for slot in range(16):
        a = _u16(data, 0xA9 + slot * 2)
        if a:
            ornaments[slot] = parse_ornament(data, a)

    order = []
    p = 0xC9
    while p < len(data) and data[p] != 0xFF:
        order.append(data[p] // 3)
        p += 1

    n_pat = (max(order) + 1) if order else 0
    patterns = []
    unknown: set = set()
    for idx in range(n_pat):
        base = ppt_off + idx * 6
        if base + 6 > len(data):            # pointer table past EOF (corrupt)
            patterns.append(([], [], []))
            continue
        a, b, c = _u16(data, base), _u16(data, base + 2), _u16(data, base + 4)
        patterns.append((decode_channel(data, a, unknown),
                         decode_channel(data, b, unknown),
                         decode_channel(data, c, unknown)))

    name = data[0x1E:0x3E].decode('ascii', 'replace').rstrip()
    author = data[0x42:0x62].decode('ascii', 'replace').rstrip()
    return Module(speed, loop_pos, order, patterns, samples, ornaments,
                  name, author, tone_table, frozenset(unknown))


@dataclass
class _Chan:
    note: int | None = None      # base PT3 note byte
    active: bool = False
    sample: int = 1
    ornament: int = 0
    vol: int = 15
    s_pos: int = 0
    o_pos: int = 0
    cr_ns_sl: int = 0            # persisted noise slide (CrNsSl)
    tn_acc: int = 0              # accumulated tone offset (TnAcc); reset per note
    env: tuple | None = None     # (shape, period) while this channel uses the env


def _positions(module: Module, loops: int, unbounded: bool):
    """Yield pattern indices in play order: one full pass, then repeat the
    `loop_pos`-onward tail (loops-1 more times, or forever if unbounded)."""
    yield from module.order
    tail = module.order[module.loop_pos:] or module.order
    if unbounded:
        while True:
            yield from tail
    else:
        for _ in range(max(0, loops - 1)):
            yield from tail


def iter_frames(module: Module, *, loops: int = 1, max_seconds: float | None = None):
    """Yield, per 50 Hz frame, ``(channels, noise_period, envelope)``.

    `channels` is a list of 3 tuples
    ``(note_index | None, amplitude 0..15, tone_on, noise_on, use_env,
    tone_ofs)`` — `note_index` is the semitone index (0 == PT3 C-1) after the
    ornament offset, amplitude already folds the channel volume into the
    sample amplitude, `use_env` is True while that channel is driven by the AY
    hardware envelope (its amplitude is then ignored — the envelope level is
    used instead), and `tone_ofs` is the sample tick's tone-period delta
    (vibrato/detune; add it to the looked-up period, positive = flatter).

    `noise_period` is the AY noise register R6 the real player would write this
    frame: ``Ns_Base + AddToNs`` (0..255; the chip uses the low 5 bits, and 0
    means hardware period 1). `Ns_Base` is only changed by the PD_NOIS pattern
    command — which spectrumizer never emits — so for its own modules the noise
    period is whatever the active samples' byte0 dictates (0 by default).

    `envelope` is ``(period, shape, retrig)`` — the AY's single envelope
    generator (R11/R12 period, R13 shape 1..14). `retrig` is True only on the
    first frame of a row that (re)wrote R13, mirroring the real player (which
    parks R13 at a no-write sentinel otherwise, so the envelope free-runs). If
    several channels enable the envelope, the highest channel's period/shape win.
    """
    speed = module.speed
    budget = None if max_seconds is None else int(max_seconds * FRAME_HZ)
    emitted = 0
    chans = [_Chan(), _Chan(), _Chan()]
    ns_base = 0          # set only by PD_NOIS (not in spectrumizer's token subset)
    add_to_ns = 0        # global noise add; persists across frames like the player

    for pidx in _positions(module, loops, unbounded=max_seconds is not None):
        if pidx >= len(module.patterns):
            continue
        chan_rows = module.patterns[pidx]
        rows = max(len(c) for c in chan_rows)
        for r in range(rows):
            row_retrig = False
            for ci in range(3):
                seq = chan_rows[ci]
                ev = seq[r] if r < len(seq) else None
                if ev is None:
                    continue
                cs = chans[ci]
                if ev.env_retrig:                   # an env token (re)set state
                    cs.env = ev.env                 # else sticky (persists, like
                    row_retrig = True               # the real player's Env_En)
                if ev.note is None:                 # OFF
                    cs.active = False
                else:
                    cs.note, cs.active = ev.note, True
                    cs.sample, cs.ornament, cs.vol = ev.sample, ev.ornament, ev.vol
                    cs.s_pos = cs.o_pos = cs.tn_acc = 0
            # the AY has a single envelope generator: the highest channel that
            # currently uses it wins its period/shape.
            env_ps = next((c.env for c in reversed(chans) if c.env is not None), None)
            env_shape = env_ps[0] if env_ps else 0
            env_period = env_ps[1] if env_ps else 0
            for _f in range(speed):
                frame = []
                for ci in range(3):              # A, B, C order: last noise tick wins
                    cs = chans[ci]
                    if not cs.active or cs.note is None:
                        frame.append((None, 0, False, False, False, 0))
                        continue
                    samp = module.samples.get(cs.sample, _DEFAULT_SAMPLE_FALLBACK)
                    orn = module.ornaments.get(cs.ornament, _DEFAULT_ORNAMENT_FALLBACK)
                    (tone_on, noise_on, s_amp, noise_path, noise_add, persist,
                     tone_add, tone_acc) = samp.at(cs.s_pos)
                    note_idx = (cs.note - 0x50) + orn.at(cs.o_pos)
                    amp = (s_amp * cs.vol) // 15
                    tone_ofs = tone_add + cs.tn_acc   # like the player: tick delta
                    if tone_acc:                      # + TnAcc, stored back if bit6
                        cs.tn_acc = tone_ofs
                    frame.append((note_idx, amp, tone_on, noise_on,
                                  cs.env is not None, tone_ofs))
                    if noise_path:               # this tick drives the AY noise period
                        add_to_ns = (noise_add + cs.cr_ns_sl) & 0xFF
                        if persist:
                            cs.cr_ns_sl = add_to_ns
                    cs.s_pos = samp.advance(cs.s_pos)
                    cs.o_pos = orn.advance(cs.o_pos)
                env = (env_period, env_shape, row_retrig and _f == 0)
                yield frame, (ns_base + add_to_ns) & 0xFF, env
                emitted += 1
                if budget is not None and emitted >= budget:
                    return
