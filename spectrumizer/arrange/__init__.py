"""Arranger: IR Song -> PT3 bytes.

Channel allocation (3 AY channels, A governs pattern length so it gets the lead):
  A = lead (top voice)
  B = bass (bottom voice)
  C = real drums if the source has them; else synth drums in chiptune style;
      else the harmony (middle voice) in faithful style.

`--style faithful|chiptune` selects which passes run — same engine, composable
passes, not two code paths.
"""

from __future__ import annotations

from ..ir import Song, Note
from ..pt3 import (
    midi_to_pt3_byte, NOTE_TO_BYTE, build_pt3,
    DEFAULT_SAMPLES, DEFAULT_ORNAMENTS,
    S_LEAD, S_BASS, S_HARMONY, S_SNARE, S_KICK, S_BUZZER, S_BUZZER_TONE,
    ORN_EMPTY, envelope_period_for,
)
from .model import Placed, rasterize, pack_patterns, ROWS_PER_PATTERN
from .quantize import plan_grid, note_rows
from .reduce import assign_voices
from .embellish import octave_short_lead, synth_drums

# GM percussion keys we treat as a kick (everything else on ch10 -> snare).
GM_KICK_KEYS = {35, 36}
DRUM_NOTE_BYTE = NOTE_TO_BYTE['C-4']     # dummy pitch; drum samples mute tone

# Default AY envelope shape for buzzer bass: 10 = \/\/ repeating triangle.
BUZZER_SHAPE = 10


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


def _drums_to_placed(drums: list[Note], rows_per_beat: int, total_rows: int,
                     ceil_vol: int = 13, vmax: int = 0) -> list[Placed]:
    out: list[Placed] = []
    for n in drums:
        s, _ = note_rows(n.start, n.end, rows_per_beat, total_rows)
        if s >= total_rows:
            continue
        sample = S_KICK if (n.pitch in GM_KICK_KEYS or n.pitch <= 36) else S_SNARE
        opts = {'sample': sample}
        if vmax > 0:
            opts['vol'] = vol_from_velocity(n.velocity, ceil_vol, vmax)
        out.append(Placed(s, s + 1, DRUM_NOTE_BYTE, opts))
    return out


def arrange(song: Song, *, style: str = 'faithful', rows_per_beat: int = 4,
            speed: int | None = None, transpose: int = 0,
            name: str | None = None, author: str = 'SPECTRUMIZER',
            loop_pos: int = 0, dynamics: bool = True,
            bass: str = 'normal') -> tuple[bytes, dict]:
    """Arrange `song` and return (pt3_bytes, stats).

    `dynamics`: map MIDI velocity to per-note AY volume (on by default); the
    loudest note in the piece sits at each channel's ceiling. False = flat
    per-channel volume.
    `bass`: 'normal' (the sampled bass), 'envelope' (pure buzzer bass — channel B
    is the AY hardware envelope itself, oscillating at each note's pitch; the
    characteristic deep AY sound, coarse pitch), or 'envelope-tone' (tone keeps
    the exact pitch, the envelope adds the buzz — pitch-accurate at any register).
    """
    speed_v, total_rows = plan_grid(song, rows_per_beat, speed)

    use_drum_channel = song.has_drums or style == 'chiptune'
    n_pitched = 2 if use_drum_channel else 3
    lead, bass_line, harmony = assign_voices(song.notes, n_pitched)

    buzzer = bass in ('envelope', 'envelope-tone')
    bass_sample = {'envelope': S_BUZZER,
                   'envelope-tone': S_BUZZER_TONE}.get(bass, S_BASS)
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
        c_p = _drums_to_placed(song.drums, rows_per_beat, total_rows, 13, dmax)
        c_sample, c_vol, c_kind = S_SNARE, 13, 'drums'
    elif style == 'chiptune':
        c_p = synth_drums(total_rows, rows_per_beat, DRUM_NOTE_BYTE, S_SNARE, S_KICK)
        c_sample, c_vol, c_kind = S_SNARE, 13, 'synth-drums'
    else:
        c_p = _line_to_placed(harmony, rows_per_beat, total_rows, transpose, 10, vmax)
        c_sample, c_vol, c_kind = S_HARMONY, 10, 'harmony'

    if style == 'chiptune':
        octave_short_lead(lead_p, short_thresh_rows=rows_per_beat)

    specs = [
        (rasterize(lead_p, total_rows), S_LEAD, 15, ORN_EMPTY),
        (rasterize(bass_p, total_rows), bass_sample, 14, ORN_EMPTY),
        (rasterize(c_p, total_rows), c_sample, c_vol, ORN_EMPTY),
    ]
    patterns = pack_patterns(specs, total_rows)

    pt3 = build_pt3(patterns, dict(DEFAULT_SAMPLES), dict(DEFAULT_ORNAMENTS),
                    name=name or song.name or "SPECTRUMIZED",
                    author=author, speed=speed_v, loop_pos=loop_pos)

    stats = {
        'style': style,
        'dynamics': dynamics,
        'bass': bass,
        'speed': speed_v,
        'rows_per_beat': rows_per_beat,
        'total_rows': total_rows,
        'patterns': len(patterns),
        'tempo_bpm': round(song.tempo_bpm, 1),
        'voices': {'lead': len(lead), 'bass': len(bass_line),
                   'channel_c': c_kind,
                   'harmony': len(harmony) if c_kind == 'harmony' else 0,
                   'drums': len(song.drums)},
        'bytes': len(pt3),
    }
    return pt3, stats
