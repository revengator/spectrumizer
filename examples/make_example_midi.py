"""Generate small example MIDIs from scratch (no downloaded files of uncertain
provenance), so the MIDIs and any .pt3 spectrumizer makes from them are clean to
redistribute:

  * ode-to-joy.mid      — Beethoven's "Ode to Joy" theme (1824), public domain.
  * pachelbel-canon.mid — Pachelbel's Canon in D (J. Pachelbel, 1653-1706),
    public domain. Its famous ground bass is the whole point of the piece, so
    voiced down into octaves 1-2 it is the ideal showcase for buzzer bass: the
    AY hardware envelope's coarse pitch still resolves the 8-note ostinato.

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

# --- Pachelbel's Canon in D (public domain) ----------------------------------
# The two-bar ground bass: D - A - Bm - F#m - G - D - G - A. Voiced low (octaves
# 1-2) so the buzzer's envelope periods stay resolvable. One cycle = 8 half notes.
D2, A1, B1, Fs1, G1, D1 = 38, 33, 35, 30, 31, 26
CANON_GROUND = [
    (D2, 2), (A1, 2), (B1, 2), (Fs1, 2),
    (G1, 2), (D1, 2), (G1, 2), (A1, 2),
]
CANON_BASS = CANON_GROUND * 3                  # three turns of the ostinato

# Violin I as three developing variations over one turn of the ground each, in
# the Canon's manner: the iconic half-note theme, then a quarter-note line, then
# eighth-note arpeggios — gradually filling in. Each step uses tones of the
# chord above it (D A Bm F#m G D G A) so the harmony is exact, and every note
# stays above the bass so the skyline reducer keeps the ground on channel B.
A5, Fs5, E5, D5, Cs5, B4, A4, G4, Fs4 = 81, 78, 76, 74, 73, 71, 69, 67, 66

CANON_V1 = [                                            # the theme (half notes)
    (Fs5, 2), (E5, 2), (D5, 2), (Cs5, 2), (B4, 2), (A4, 2), (B4, 2), (Cs5, 2),
]
CANON_V2 = [                                            # quarter notes, 2 per chord
    (Fs5, 1), (A5, 1),  (E5, 1), (Cs5, 1),  (D5, 1), (Fs5, 1),  (Cs5, 1), (A4, 1),
    (B4, 1),  (D5, 1),  (Fs5, 1), (A4, 1),  (B4, 1), (D5, 1),   (Cs5, 1), (E5, 1),
]
CANON_V3 = [                                            # eighth-note arpeggios
    (D5, .5), (Fs5, .5), (A5, .5), (Fs5, .5),  (Cs5, .5), (E5, .5), (A5, .5), (E5, .5),
    (B4, .5), (D5, .5),  (Fs5, .5), (D5, .5),  (Fs4, .5), (A4, .5), (Cs5, .5), (A4, .5),
    (G4, .5), (B4, .5),  (D5, .5), (B4, .5),   (D5, .5),  (Fs5, .5), (A5, .5), (Fs5, .5),
    (G4, .5), (B4, .5),  (D5, .5), (B4, .5),   (A4, .5),  (Cs5, .5), (E5, .5), (Cs5, .5),
]
CANON_MELODY = CANON_V1 + CANON_V2 + CANON_V3


def _add_voice(track, events, channel, velocity):
    delay = 0                                  # carry rest duration to next onset
    for note, beats in events:
        ticks = int(round(beats * TPB))
        if note is None:                       # a rest
            delay += ticks
            continue
        track.append(mido.Message('note_on', note=note, velocity=velocity,
                                  channel=channel, time=delay))
        track.append(mido.Message('note_off', note=note, velocity=0,
                                  channel=channel, time=ticks))
        delay = 0


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
        'pachelbel-canon.mid': _build('Canon in D', 100, CANON_MELODY, CANON_BASS,
                                      mel_vel=88, bass_vel=104),
    }
    for fname, mid in files.items():
        out = os.path.join(here, fname)
        mid.save(out)
        print(f"wrote {out}")


if __name__ == '__main__':
    main()
