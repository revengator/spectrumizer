"""MIDI -> IR adapter (uses `mido`).

Merges all tracks into one absolute timeline, pairs note-on/note-off per
(channel, note), routes GM channel 10 (0-based index 9) to drums, and converts
tick times to beats via the file's ticks-per-beat. MVP limitation: tempo is read
once (first set_tempo); a tempo map is not applied — a warning is emitted if the
source changes tempo mid-piece.
"""

from __future__ import annotations

import sys

import mido

from ..ir import Note, Song

GM_DRUM_CHANNEL = 9             # 0-based; MIDI "channel 10"


def load_midi(path: str) -> Song:
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat or 480

    tempos: list[int] = []          # microseconds per beat, in order seen
    notes: list[Note] = []
    drums: list[Note] = []
    # open notes keyed by (channel, pitch) -> (start_beat, velocity)
    open_notes: dict[tuple[int, int], tuple[float, int]] = {}

    abs_ticks = 0
    for msg in mido.merge_tracks(mid.tracks):
        abs_ticks += msg.time
        beat = abs_ticks / tpb

        if msg.type == 'set_tempo':
            tempos.append(msg.tempo)
            continue
        if msg.type == 'note_on' and msg.velocity > 0:
            open_notes[(msg.channel, msg.note)] = (beat, msg.velocity)
            continue
        if msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            key = (msg.channel, msg.note)
            started = open_notes.pop(key, None)
            if started is None:
                continue
            start, vel = started
            dur = max(beat - start, 1e-6)
            note = Note(pitch=msg.note, start=start, dur=dur, velocity=vel,
                        track=msg.channel)
            (drums if msg.channel == GM_DRUM_CHANNEL else notes).append(note)

    # Any notes still held at EOF: close them at the last event time.
    if open_notes:
        end_beat = abs_ticks / tpb
        for (chan, pitch), (start, vel) in open_notes.items():
            dur = max(end_beat - start, 1e-6)
            note = Note(pitch=pitch, start=start, dur=dur, velocity=vel, track=chan)
            (drums if chan == GM_DRUM_CHANNEL else notes).append(note)

    if len(tempos) > 1 and len(set(tempos)) > 1:
        print("spectrumizer: warning: source has tempo changes; using the first "
              "tempo only (MVP). Consider --speed to set the row rate manually.",
              file=sys.stderr)

    tempo_us = tempos[0] if tempos else 500000        # default 120 BPM
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
