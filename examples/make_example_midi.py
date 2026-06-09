"""Generate a small PUBLIC-DOMAIN example MIDI (no downloaded file of uncertain
provenance). Beethoven's "Ode to Joy" theme (1824) — composition is public
domain. We synthesise the notes ourselves, so the resulting MIDI and any .pt3
spectrumizer makes from it are clean to redistribute.

    python examples/make_example_midi.py        # -> examples/ode-to-joy.mid
"""

from __future__ import annotations

import os

import mido

# Melody (treble), MIDI note numbers, as (note, beats). Two 4-bar phrases.
E4, F4, G4, D4, C4 = 64, 65, 67, 62, 60
MELODY = [
    (E4, 1), (E4, 1), (F4, 1), (G4, 1),
    (G4, 1), (F4, 1), (E4, 1), (D4, 1),
    (C4, 1), (C4, 1), (D4, 1), (E4, 1),
    (E4, 1.5), (D4, 0.5), (D4, 2),
    (E4, 1), (E4, 1), (F4, 1), (G4, 1),
    (G4, 1), (F4, 1), (E4, 1), (D4, 1),
    (C4, 1), (C4, 1), (D4, 1), (E4, 1),
    (D4, 1.5), (C4, 0.5), (C4, 2),
]

# Simple root bass, one note per bar (4/4), under the chords I/IV/V.
C3, F3, G3 = 48, 53, 55
BASS = [
    (C3, 4), (C3, 4), (C3, 4), (G3, 4),
    (C3, 4), (C3, 4), (C3, 4), (C3, 4),
]

TPB = 480


def _add_voice(track, events, channel, velocity):
    for note, beats in events:
        ticks = int(round(beats * TPB))
        track.append(mido.Message('note_on', note=note, velocity=velocity,
                                  channel=channel, time=0))
        track.append(mido.Message('note_off', note=note, velocity=0,
                                  channel=channel, time=ticks))


def main():
    mid = mido.MidiFile(ticks_per_beat=TPB)

    melody = mido.MidiTrack(); mid.tracks.append(melody)
    melody.append(mido.MetaMessage('track_name', name='Ode to Joy', time=0))
    melody.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120), time=0))
    _add_voice(melody, MELODY, channel=0, velocity=100)

    bass = mido.MidiTrack(); mid.tracks.append(bass)
    _add_voice(bass, BASS, channel=1, velocity=80)

    out = os.path.join(os.path.dirname(__file__), 'ode-to-joy.mid')
    mid.save(out)
    print(f"wrote {out}")


if __name__ == '__main__':
    main()
