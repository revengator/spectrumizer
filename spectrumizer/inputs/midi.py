"""MIDI -> IR adapter (uses `mido`).

Merges all tracks into one absolute timeline, pairs note-on/note-off per
(channel, note), routes GM channel 10 (0-based index 9) to drums, and converts
tick times to beats via the file's ticks-per-beat.

Tempo changes are folded into one fixed grid (PT3 has a single global speed):
the dominant tempo — the one heard longest — becomes the reference, and every
other section's ticks are scaled by its tempo ratio, so wall-clock timing is
preserved (a half-tempo bar simply lasts twice as many rows).
"""

from __future__ import annotations

import bisect
import sys

import mido

from ..ir import Note, Song

GM_DRUM_CHANNEL = 9             # 0-based; MIDI "channel 10"
DEFAULT_TEMPO_US = 500000       # the MIDI default: 120 bpm


def _tempo_map(changes: list[tuple[int, int]], tpb: int, end_tick: int):
    """Build the tick -> reference-beat conversion from a tempo map.

    `changes` are (abs_tick, us_per_beat) in order. Returns
    (to_beat, ref_us, n_distinct): the reference is the tempo active the
    longest (by wall-clock time); within each segment ticks advance the
    reference beat by the segment's tempo ratio, preserving seconds.
    """
    segs: list[tuple[int, int]] = []
    if not changes or changes[0][0] > 0:
        segs.append((0, DEFAULT_TEMPO_US))
    for tick, us in changes:
        if segs and segs[-1][0] == tick:
            segs[-1] = (tick, us)           # same-tick changes: last one wins
        elif segs and segs[-1][1] == us:
            continue                        # the same tempo re-emitted
        else:
            segs.append((tick, us))

    if len({us for _, us in segs}) == 1:    # constant tempo: plain ticks/beat
        return (lambda t: t / tpb), segs[0][1], 1

    weight: dict[int, int] = {}             # us -> wall-clock ticks*us
    for i, (tick, us) in enumerate(segs):
        nxt = segs[i + 1][0] if i + 1 < len(segs) else max(end_tick, tick)
        weight[us] = weight.get(us, 0) + (nxt - tick) * us
    ref = max(weight, key=lambda u: weight[u])

    starts: list[int] = []
    warped: list[float] = []
    ratios: list[float] = []
    acc = 0.0
    for i, (tick, us) in enumerate(segs):
        starts.append(tick); warped.append(acc); ratios.append(us / ref)
        if i + 1 < len(segs):
            acc += ((segs[i + 1][0] - tick) / tpb) * (us / ref)

    def to_beat(t: int) -> float:
        i = bisect.bisect_right(starts, t) - 1
        return warped[i] + ((t - starts[i]) / tpb) * ratios[i]

    return to_beat, ref, len(weight)


def load_midi(path: str) -> Song:
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat or 480

    # Pass 1: absolute timeline — note events and the tempo map.
    raw: list[tuple[int, mido.Message]] = []
    changes: list[tuple[int, int]] = []     # (abs_tick, us_per_beat)
    abs_ticks = 0
    for msg in mido.merge_tracks(mid.tracks):
        abs_ticks += msg.time
        if msg.type == 'set_tempo':
            changes.append((abs_ticks, msg.tempo))
        elif msg.type in ('note_on', 'note_off'):
            raw.append((abs_ticks, msg))

    to_beat, tempo_us, n_tempos = _tempo_map(changes, tpb, abs_ticks)
    if n_tempos > 1:
        print(f"spectrumizer: tempo map: {n_tempos} tempos folded into a fixed "
              f"~{60_000_000 / tempo_us:.0f} bpm grid (wall-clock timing kept).",
              file=sys.stderr)

    # Pass 2: pair note-on/note-off on the (tempo-warped) beat timeline.
    notes: list[Note] = []
    drums: list[Note] = []
    # open notes keyed by (channel, pitch) -> (start_beat, velocity)
    open_notes: dict[tuple[int, int], tuple[float, int]] = {}

    def close(chan: int, pitch: int, start: float, vel: int, end: float) -> None:
        dur = max(end - start, 1e-6)
        note = Note(pitch=pitch, start=start, dur=dur, velocity=vel, track=chan)
        (drums if chan == GM_DRUM_CHANNEL else notes).append(note)

    for tick, msg in raw:
        beat = to_beat(tick)
        if msg.type == 'note_on' and msg.velocity > 0:
            key = (msg.channel, msg.note)
            started = open_notes.pop(key, None)
            if started is not None:     # same pitch re-struck while sounding:
                close(msg.channel, msg.note, *started, beat)   # close, don't drop
            open_notes[key] = (beat, msg.velocity)
        else:                           # note_off, or note_on with velocity 0
            started = open_notes.pop((msg.channel, msg.note), None)
            if started is not None:
                close(msg.channel, msg.note, *started, beat)

    # Any notes still held at EOF: close them at the last event time.
    end_beat = to_beat(abs_ticks)
    for (chan, pitch), (start, vel) in open_notes.items():
        close(chan, pitch, start, vel, end_beat)

    tempo_bpm = 60_000_000 / tempo_us

    notes.sort(key=lambda n: (n.start, n.pitch))
    drums.sort(key=lambda n: n.start)

    name = ""
    for tr in mid.tracks:
        for msg in tr:
            if msg.type == 'track_name' and msg.name.strip():
                name = msg.name.strip()
                break
        if name:
            break

    return Song(notes=notes, drums=drums, tempo_bpm=tempo_bpm, name=name)
