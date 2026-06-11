"""Arranger: IR Song -> PT3 bytes.

Channel allocation (3 AY channels, A governs pattern length so it gets the lead):
  A = lead (top voice)
  B = bass (bottom voice)
  C = real drums if the source has them (the harmony fills the rows between
      hits); else synth drums in chiptune style; else the harmony (middle
      voice) in faithful style.

`--style faithful|chiptune` selects which passes run — same engine, composable
passes, not two code paths.
"""

from __future__ import annotations

from ..ir import Song, Note
from ..pt3 import (
    midi_to_pt3_byte, NOTE_TO_BYTE, build_pt3,
    DEFAULT_SAMPLES, DEFAULT_ORNAMENTS, arp_ornaments,
    S_LEAD, S_BASS, S_HARMONY, S_SNARE, S_KICK, S_BUZZER, S_BUZZER_TONE,
    S_LEAD_VIB, S_HAT, S_HAT_OPEN, ORN_EMPTY, envelope_period_for,
)
from .model import Placed, rasterize, pack_patterns, ROWS_PER_PATTERN
from .quantize import plan_grid, note_rows
from .reduce import assign_voices
from .embellish import (octave_short_lead, synth_drums, chord_arps, echo_lead,
                        multiplex_drums_harmony)

# GM percussion mapping: kicks and snares carry the groove at the full drum
# level; cymbals tick behind them, quieter (closed hats lowest). Anything on
# ch10 we don't recognise is a snare-ish hit.
GM_KICK_KEYS = {35, 36}
GM_HAT_KEYS = {42, 44, 51, 53, 59}        # closed/pedal hi-hat + ride family
GM_HAT_OPEN_KEYS = {46, 49, 52, 55, 57}   # open hi-hat + crash family
DRUM_NOTE_BYTE = NOTE_TO_BYTE['C-4']     # dummy pitch; drum samples mute tone

# Simultaneous GM hits collapse to one per row (the AY gives the drums a single
# voice): the groove carriers outrank the cymbals.
_DRUM_RANK = {S_KICK: 3, S_SNARE: 2, S_HAT_OPEN: 1, S_HAT: 0}

# Default AY envelope shape for buzzer bass: 10 = \/\/ repeating triangle.
BUZZER_SHAPE = 10

# The AY's comfortable register, as MIDI numbers under the standard PT3 mapping
# (midi_to_pt3_byte): from the format floor (C-1 — notes below it fold and break
# contours; deep basses are fine, the tone table resolves them) up to B-6, clear
# of octaves 7-8 where the tiny tone periods turn audibly out of tune. The
# centre is calibrated so every bundled hand-registered example auto-shifts 0.
AUTO_RANGE = (24, 95)
AUTO_CENTER = 57      # where a piece's duration-weighted mean pitch sits best


def auto_transpose_shift(notes: list[Note]) -> int:
    """The octave shift (semitones, a multiple of 12) that best fits the
    pitched notes into the AY's comfortable register.

    Octave shifts only, so the key is preserved. Maximises the note-duration
    landing inside AUTO_RANGE; ties prefer the shift that centres the
    duration-weighted mean pitch on AUTO_CENTER, then the smallest move.
    """
    if not notes:
        return 0
    weight = sum(n.dur for n in notes)
    mean = (sum(n.pitch * n.dur for n in notes) / weight) if weight else \
        sum(n.pitch for n in notes) / len(notes)
    lo, hi = AUTO_RANGE

    def score(k: int) -> tuple:
        sh = 12 * k
        inside = sum(n.dur for n in notes if lo <= n.pitch + sh <= hi)
        return (inside, -abs(mean + sh - AUTO_CENTER), -abs(k))

    return 12 * max(range(-5, 6), key=score)


def vol_from_velocity(velocity: int, ceil: int, vmax: int) -> int:
    """Map a MIDI velocity to an AY volume in 1..ceil, scaled so the piece's
    loudest note reaches the channel's ceiling. `vmax <= 0` disables dynamics
    (returns the ceiling), so a flat-velocity source stays at full volume."""
    if vmax <= 0:
        return ceil
    return max(1, min(ceil, round(ceil * velocity / vmax)))


def _line_to_placed(line: list[Note], rows_per_beat: int, total_rows: int,
                    transpose: int, ceil_vol: int = 15, vmax: int = 0,
                    env_shape: int | None = None, tone_table: list | None = None
                    ) -> list[Placed]:
    out: list[Placed] = []
    for n in line:
        s, e = note_rows(n.start, n.end, rows_per_beat, total_rows)
        if s >= total_rows:
            continue
        note_byte = midi_to_pt3_byte(n.pitch, transpose)
        opts = {} if vmax <= 0 else {'vol': vol_from_velocity(n.velocity, ceil_vol, vmax)}
        if env_shape is not None:               # buzzer bass: drive the note from
            ep = envelope_period_for(tone_table[note_byte - 0x50], env_shape)
            opts['env'] = (env_shape, ep)       # the hardware envelope at its pitch
        out.append(Placed(s, e, note_byte, opts))
    return out


def _gm_drum(pitch: int) -> tuple[int, int]:
    """GM percussion key -> (sample, AY volume ceiling)."""
    if pitch in GM_KICK_KEYS or pitch <= 36:
        return S_KICK, 13
    if pitch in GM_HAT_KEYS:
        return S_HAT, 10
    if pitch in GM_HAT_OPEN_KEYS:
        return S_HAT_OPEN, 11
    return S_SNARE, 13


def _drums_to_placed(drums: list[Note], rows_per_beat: int, total_rows: int,
                     vmax: int = 0) -> list[Placed]:
    """GM drum notes -> one-row hits, each stating its own sample and volume
    (the channel is shared, so the encoder must see every change). Hits that
    quantise to the same row collapse to the highest-ranked one."""
    by_row: dict[int, Placed] = {}
    for n in drums:
        s, _ = note_rows(n.start, n.end, rows_per_beat, total_rows)
        if s >= total_rows:
            continue
        sample, ceil = _gm_drum(n.pitch)
        cur = by_row.get(s)
        if cur is not None and _DRUM_RANK[cur.opts['sample']] >= _DRUM_RANK[sample]:
            continue
        by_row[s] = Placed(s, s + 1, DRUM_NOTE_BYTE,
                           {'sample': sample,
                            'vol': vol_from_velocity(n.velocity, ceil, vmax)})
    return [by_row[r] for r in sorted(by_row)]


def arrange(song: Song, *, style: str = 'faithful', rows_per_beat: int = 4,
            speed: int | None = None, transpose: int = 0,
            auto_transpose: bool = False,
            name: str | None = None, author: str = 'SPECTRUMIZER',
            loop_pos: int = 0, dynamics: bool = True,
            bass: str = 'normal', arps: bool = False, arp_speed: int = 1,
            echo: bool = False, vibrato: bool = False) -> tuple[bytes, dict]:
    """Arrange `song` and return (pt3_bytes, stats).

    `dynamics`: map MIDI velocity to per-note AY volume (on by default); the
    loudest note in the piece sits at each channel's ceiling. False = flat
    per-channel volume.
    `bass`: 'normal' (the sampled bass), 'envelope' (pure buzzer bass — channel B
    is the AY hardware envelope itself, oscillating at each note's pitch; the
    characteristic deep AY sound, coarse pitch), or 'envelope-tone' (tone keeps
    the exact pitch, the envelope adds the buzz — pitch-accurate at any register).
    `arps`: route channel C to chord arpeggios — each source chord becomes its
    root + an interval ornament (major/minor triads, dominant/major/minor
    sevenths, sus2/sus4) cycling at frame rate, faking the full chord on one
    channel. Real drums in the source still take channel C; otherwise arps
    replace the harmony / synth-drums voice there.
    `arp_speed`: frames each arp chord tone holds (default 1 = the classic
    50 Hz blur; higher rates ripple audibly).
    `echo`: route channel C to a delayed, quieter copy of the lead (the classic
    AY echo: half a beat later at ~8/15 volume, same timbre). Outranked by real
    drums and by `arps`.
    `vibrato`: give the lead (and an echo, which mirrors its timbre) the
    delayed-vibrato sample — the sustain wobbles the tone period ±3 units at
    6.25 Hz, encoded per tick inside the sample so it costs nothing in the
    patterns.
    `auto_transpose`: shift the piece by whole octaves so its range sits in
    the AY's comfortable register (see `auto_transpose_shift`); `transpose`
    is then applied on top as a manual offset.
    """
    speed_v, total_rows = plan_grid(song, rows_per_beat, speed)
    if auto_transpose:
        transpose += auto_transpose_shift(song.notes)

    # Channel C: drums win; then arps; then echo; then synth-drums / harmony.
    # With real drums the harmony is multiplexed into the gaps between hits,
    # so the reduction still extracts 3 voices in that case.
    arps = arps and not song.has_drums
    echo = echo and not song.has_drums and not arps
    c_exclusive = arps or echo or (style == 'chiptune' and not song.has_drums)
    n_pitched = 2 if c_exclusive else 3
    lead, bass_line, harmony = assign_voices(song.notes, n_pitched)

    buzzer = bass in ('envelope', 'envelope-tone')
    bass_sample = {'envelope': S_BUZZER,
                   'envelope-tone': S_BUZZER_TONE}.get(bass, S_BASS)
    lead_sample = S_LEAD_VIB if vibrato else S_LEAD
    tone_table = None
    if buzzer:
        from ..audio import build_pt3_table     # the exact PT3 tone periods
        tone_table = build_pt3_table()

    vmax = max((n.velocity for n in song.notes), default=0) if dynamics else 0
    lead_p = _line_to_placed(lead, rows_per_beat, total_rows, transpose, 15, vmax)
    bass_p = _line_to_placed(bass_line, rows_per_beat, total_rows, transpose, 14, vmax,
                             env_shape=BUZZER_SHAPE if buzzer else None,
                             tone_table=tone_table)

    if song.has_drums:
        dmax = max((n.velocity for n in song.drums), default=0) if dynamics else 0
        drums_p = _drums_to_placed(song.drums, rows_per_beat, total_rows, dmax)
        harm_p = _line_to_placed(harmony, rows_per_beat, total_rows, transpose,
                                 10, vmax)
        # both voices share the channel, so every event states its own timbre
        # and volume (the encoder only emits tokens on change)
        for p in harm_p:
            p.opts['sample'] = S_HARMONY
            p.opts.setdefault('vol', 10)
        c_p = multiplex_drums_harmony(drums_p, harm_p)
        c_sample, c_vol = S_SNARE, 13
        c_kind = 'drums+harmony' if harm_p else 'drums'
    elif arps:
        vol_fn = (lambda v: vol_from_velocity(v, 10, vmax)) if vmax > 0 else None
        c_p = chord_arps(song.notes, rows_per_beat, total_rows, transpose, vol_fn)
        c_sample, c_vol, c_kind = S_HARMONY, 10, 'arp'
    elif echo:
        c_p = []                        # built below, after the lead embellishment
        c_sample, c_vol, c_kind = lead_sample, 8, 'echo'
    elif style == 'chiptune':
        c_p = synth_drums(total_rows, rows_per_beat, DRUM_NOTE_BYTE,
                          S_SNARE, S_KICK, S_HAT, S_HAT_OPEN)
        c_sample, c_vol, c_kind = S_SNARE, 13, 'synth-drums'
    else:
        c_p = _line_to_placed(harmony, rows_per_beat, total_rows, transpose, 10, vmax)
        c_sample, c_vol, c_kind = S_HARMONY, 10, 'harmony'

    if style == 'chiptune':
        octave_short_lead(lead_p, short_thresh_rows=rows_per_beat)
    if c_kind == 'echo':                # after octave_short_lead, so the echo
        c_p = echo_lead(lead_p,         # carries the lead's ornaments too
                        max(1, rows_per_beat // 2), total_rows)

    specs = [
        (rasterize(lead_p, total_rows), lead_sample, 15, ORN_EMPTY),
        (rasterize(bass_p, total_rows), bass_sample, 14, ORN_EMPTY),
        (rasterize(c_p, total_rows), c_sample, c_vol, ORN_EMPTY),
    ]
    patterns = pack_patterns(specs, total_rows)

    # Deduplicate identical patterns through the PT3 position list (store each
    # once, replay by index). Safe on byte equality: every pattern re-emits its
    # initial volume / sample / ornament / NtSkip state (see pt3.encode), so
    # identical bytes mean identical playback.
    unique: list[tuple[bytes, bytes, bytes]] = []
    index: dict[tuple[bytes, bytes, bytes], int] = {}
    order = []
    for pat in patterns:
        if pat not in index:
            index[pat] = len(unique)
            unique.append(pat)
        order.append(index[pat])

    ornaments = dict(DEFAULT_ORNAMENTS)
    arp_speed = max(1, arp_speed)
    if arp_speed != 1:                  # slower arps: rebuild the arp ornaments
        ornaments.update(arp_ornaments(arp_speed))

    pt3 = build_pt3(unique, dict(DEFAULT_SAMPLES), ornaments,
                    name=name or song.name or "SPECTRUMIZED",
                    author=author, speed=speed_v, order=order, loop_pos=loop_pos)

    stats = {
        'style': style,
        'dynamics': dynamics,
        'transpose': transpose,
        'auto_transpose': auto_transpose,
        'bass': bass,
        'arps': arps,
        'arp_speed': arp_speed,
        'echo': echo,
        'vibrato': vibrato,
        'speed': speed_v,
        'rows_per_beat': rows_per_beat,
        'total_rows': total_rows,
        'patterns': len(unique),
        'positions': len(order),
        'tempo_bpm': round(song.tempo_bpm, 1),
        'voices': {'lead': len(lead), 'bass': len(bass_line),
                   'channel_c': c_kind,
                   'harmony': (len(harmony)
                               if c_kind in ('harmony', 'drums+harmony') else 0),
                   'arp': len(c_p) if c_kind == 'arp' else 0,
                   'echo': len(c_p) if c_kind == 'echo' else 0,
                   'drums': len(song.drums)},
        'bytes': len(pt3),
    }
    return pt3, stats
