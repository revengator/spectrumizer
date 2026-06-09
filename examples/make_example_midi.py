"""Generate small example MIDIs from scratch (no downloaded files of uncertain
provenance), so the MIDIs and any .pt3 spectrumizer makes from them are clean to
redistribute:

  * ode-to-joy.mid  — Beethoven's "Ode to Joy" theme (1824), public domain.
  * bass-groove.mid — an ORIGINAL low-bass groove (© the author, MIT with the
    rest of the repo) that showcases buzzer bass: the bass sits in octaves 1-2,
    where the AY hardware envelope's coarse pitch still resolves into distinct
    steps and sounds musical.

    python examples/make_example_midi.py
"""

from __future__ import annotations

import os

import mido

TPB = 480

# --- Ode to Joy (public domain) ----------------------------------------------
# Melody (treble), MIDI note numbers, as (note, beats). Two 4-bar phrases.
E4, F4, G4, D4, C4 = 64, 65, 67, 62, 60
ODE_MELODY = [
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
ODE_BASS = [
    (C3, 4), (C3, 4), (C3, 4), (G3, 4),
    (C3, 4), (C3, 4), (C3, 4), (C3, 4),
]

# --- Original buzzer groove (own composition) --------------------------------
# i-VI-III-VII in A minor; the bass arpeggiates root / octave / fifth down in
# octaves 1-2 so each step lands on a distinct AY envelope period.
A1, A2, E2, F1, F2, C2, C1, G1, G2, D2 = 33, 45, 40, 29, 41, 36, 24, 31, 43, 38
GROOVE_BASS = [
    (A1, 1), (A2, 1), (E2, 1), (A2, 1),     # Am
    (F1, 1), (F2, 1), (C2, 1), (F2, 1),     # F
    (C2, 1), (C1, 1), (G1, 1), (C1, 1),     # C  (C1 = a deep octave-down thud)
    (G1, 1), (G2, 1), (D2, 1), (G2, 1),     # G
] * 2

# Sparse lead on top so the buzzer bass stays the star.
A4, C5, G4, D5, B4 = 69, 72, 67, 74, 71
GROOVE_LEAD = [
    (A4, 2), (C5, 2), (C5, 2), (A4, 2),
    (G4, 2), (E4, 2), (D5, 2), (B4, 2),
] * 2


def _add_voice(track, events, channel, velocity):
    for note, beats in events:
        ticks = int(round(beats * TPB))
        track.append(mido.Message('note_on', note=note, velocity=velocity,
                                  channel=channel, time=0))
        track.append(mido.Message('note_off', note=note, velocity=0,
                                  channel=channel, time=ticks))


def _build(name: str, tempo: int, melody: list, bass: list,
           mel_vel: int = 100, bass_vel: int = 80) -> mido.MidiFile:
    mid = mido.MidiFile(ticks_per_beat=TPB)
    lead = mido.MidiTrack(); mid.tracks.append(lead)
    lead.append(mido.MetaMessage('track_name', name=name, time=0))
    lead.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo), time=0))
    _add_voice(lead, melody, channel=0, velocity=mel_vel)
    low = mido.MidiTrack(); mid.tracks.append(low)
    _add_voice(low, bass, channel=1, velocity=bass_vel)
    return mid


def main():
    here = os.path.dirname(__file__)
    files = {
        'ode-to-joy.mid': _build('Ode to Joy', 120, ODE_MELODY, ODE_BASS),
        'bass-groove.mid': _build('Bass Groove', 132, GROOVE_LEAD, GROOVE_BASS,
                                  mel_vel=82, bass_vel=104),
    }
    for fname, mid in files.items():
        out = os.path.join(here, fname)
        mid.save(out)
        print(f"wrote {out}")


if __name__ == '__main__':
    main()
