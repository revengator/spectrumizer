"""Generate small example MIDIs from scratch (no downloaded files of uncertain
provenance), so the MIDIs and any .pt3 spectrumizer makes from them are clean to
redistribute:

  * ode-to-joy.mid      — Beethoven's "Ode to Joy" theme (1824), public domain.
  * pachelbel-canon.mid — Pachelbel's Canon in D (J. Pachelbel, 1653-1706),
    public domain. Its famous ground bass is the whole point of the piece, so
    voiced down into octaves 1-2 it is the ideal showcase for buzzer bass: the
    AY hardware envelope's coarse pitch still resolves the 8-note ostinato.
  * korobeiniki.mid     — "Korobeiniki" (Russian folk song, 1861), public
    domain — the tune Tetris made famous. Ours is an original arrangement
    with a real GM drum track (channel 10), so it exercises the
    drums + harmony time-share on channel C.

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

# --- Korobeiniki (Russian folk song, 1861; public domain) ---------------------
# The tune Tetris made famous, in A minor: 8 bars of 4/4 (32 beats). Chords:
# Am Am E Am | Dm Am E Am. Four voices: melody (ch0), an octave-pumping bass
# (ch1), a held chord line (ch2) and a kick/snare/hi-hat groove on the GM drum
# channel (ch9) — the drum track is what showcases the channel-C time-share.
A5K, G5K, F5K, E5K, D5K, C5K, B4K, A4K = 81, 79, 77, 76, 74, 72, 71, 69
KORO_MELODY = [
    (E5K, 1), (B4K, .5), (C5K, .5), (D5K, 1), (C5K, .5), (B4K, .5),
    (A4K, 1), (A4K, .5), (C5K, .5), (E5K, 1), (D5K, .5), (C5K, .5),
    (B4K, 1.5), (C5K, .5), (D5K, 1), (E5K, 1),
    (C5K, 1), (A4K, 1), (A4K, 2),
    (None, .5), (D5K, 1), (F5K, .5), (A5K, 1), (G5K, .5), (F5K, .5),
    (E5K, 1.5), (C5K, .5), (E5K, 1), (D5K, .5), (C5K, .5),
    (B4K, 1), (B4K, .5), (C5K, .5), (D5K, 1), (E5K, 1),
    (C5K, 1), (A4K, 1), (A4K, 1), (None, 1),
]

# Bass: chiptune octave pumping, eighth notes root / root+12, one root per bar.
_KORO_ROOTS = [45, 45, 40, 45, 38, 45, 40, 45]          # A2 A2 E2 A2 D2 A2 E2 A2
KORO_BASS = [ev for r in _KORO_ROOTS for ev in ((r, .5), (r + 12, .5)) * 4]

# Chord line: two half notes per bar (third/fifth of the bar's chord), kept
# between the bass and the melody so the skyline reduction makes it the harmony.
_KORO_CHORD = {'Am': ((60, 2), (64, 2)),                # C4, E4
               'E':  ((56, 2), (59, 2)),                # G#3, B3
               'Dm': ((62, 2), (65, 2))}                # D4, F4
KORO_HARMONY = [ev for ch in ('Am', 'Am', 'E', 'Am', 'Dm', 'Am', 'E', 'Am')
                for ev in _KORO_CHORD[ch]]

# Drums (GM ch10): kick 36 on beats 1 & 3, snare 38 on 2 & 4, closed hi-hat 42
# on every off-eighth with an open hat 46 closing the bar, snare fill at the end.
_KORO_BAR = [(36, .25), (None, .25), (42, .25), (None, .25),
             (38, .25), (None, .25), (42, .25), (None, .25),
             (36, .25), (None, .25), (42, .25), (None, .25),
             (38, .25), (None, .25), (46, .25), (None, .25)]
_KORO_FILL = _KORO_BAR[:13] + [(None, .25), (38, .25), (None, .25)]
KORO_DRUMS = _KORO_BAR * 7 + _KORO_FILL


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
           mel_vel: int = 100, bass_vel: int = 80,
           harmony: list | None = None, harm_vel: int = 72,
           drums: list | None = None, drum_vel: int = 110) -> mido.MidiFile:
    mid = mido.MidiFile(ticks_per_beat=TPB)
    lead = mido.MidiTrack(); mid.tracks.append(lead)
    lead.append(mido.MetaMessage('track_name', name=name, time=0))
    lead.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo), time=0))
    _add_voice(lead, melody, channel=0, velocity=mel_vel)
    low = mido.MidiTrack(); mid.tracks.append(low)
    _add_voice(low, bass, channel=1, velocity=bass_vel)
    if harmony:
        chords = mido.MidiTrack(); mid.tracks.append(chords)
        _add_voice(chords, harmony, channel=2, velocity=harm_vel)
    if drums:
        kit = mido.MidiTrack(); mid.tracks.append(kit)
        _add_voice(kit, drums, channel=9, velocity=drum_vel)
    return mid


def main():
    here = os.path.dirname(__file__)
    files = {
        'ode-to-joy.mid': _build('Ode to Joy', 120, ODE_MELODY, ODE_BASS),
        'pachelbel-canon.mid': _build('Canon in D', 125, CANON_MELODY, CANON_BASS,
                                      mel_vel=88, bass_vel=104),
        'korobeiniki.mid': _build('Korobeiniki', 150, KORO_MELODY, KORO_BASS,
                                  bass_vel=92, harmony=KORO_HARMONY,
                                  drums=KORO_DRUMS),
    }
    for fname, mid in files.items():
        out = os.path.join(here, fname)
        mid.save(out)
        print(f"wrote {out}")


if __name__ == '__main__':
    main()
