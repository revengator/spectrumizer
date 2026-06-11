"""Chord detection for the arpeggio embellisher.

The arranger reduces polyphony to monophonic lines (`reduce.assign_voices`), so a
source chord normally loses everything but its skyline note. Chord arpeggios buy
that polyphony back on a single channel: identify the chord sounding at an onset,
play its root, and cycle the matching interval ornament (root, +third, +fifth,
+seventh...) at frame rate so the one channel implies the whole chord (the
classic AY/Follin trick — see `pt3.ornaments`).

This module only *recognises* chords from a pitch set; building the arp line is
`embellish.chord_arps`.
"""

from __future__ import annotations

from ..ir import Note

# Quality -> the intervals its arp ornament cycles (mirrors pt3.ARP_INTERVALS).
_CHORD_TONES = {
    'maj': {0, 4, 7}, 'min': {0, 3, 7},
    'dom7': {0, 4, 7, 10}, 'maj7': {0, 4, 7, 11}, 'min7': {0, 3, 7, 10},
    'sus2': {0, 2, 7}, 'sus4': {0, 5, 7},
}


def _quality(iv: set[int]) -> str | None:
    """The chord quality of an interval set over a candidate root."""
    if 4 in iv:
        if 10 in iv:
            return 'dom7'
        if 11 in iv:
            return 'maj7'
        return 'maj'
    if 3 in iv:
        return 'min7' if 10 in iv else 'min'
    if 7 in iv:                      # no third: a suspension needs the fifth
        if 5 in iv:
            return 'sus4'
        if 2 in iv:
            return 'sus2'
    return None


def identify_chord(pitches: list[int]) -> tuple[int, str] | None:
    """Recognise the chord in a set of MIDI pitches.

    Returns (root_pitch_class, quality) with quality one of 'maj', 'min',
    'dom7', 'maj7', 'min7', 'sus2', 'sus4' — the qualities the arp ornaments
    cover — or None when nothing matches (fewer than 2 distinct pitch classes,
    or no third/suspension over any candidate root). The root whose chord
    tones cover most of the pitch set wins; ties prefer the root that matches
    the bass note (so sus2/sus4 inversions read from the bass).
    """
    pcs = sorted({p % 12 for p in pitches})
    if len(pcs) < 2:
        return None
    bass_pc = min(pitches) % 12
    best_key: tuple[int, int] | None = None
    best: tuple[int, str] | None = None
    for root in pcs:
        iv = {(pc - root) % 12 for pc in pcs}
        quality = _quality(iv)
        if quality is None:
            continue
        # the reading that explains more of the notes beats a partial match;
        # root==bass breaks ties (root position / bass-led suspensions).
        key = (len(iv & _CHORD_TONES[quality]), 1 if root == bass_pc else 0)
        if best_key is None or key > best_key:
            best_key, best = key, (root, quality)
    return best


def group_by_onset(notes: list[Note], key=None) -> list[list[Note]]:
    """Group notes that attack together, in onset order.

    `key` maps an onset (in beats) to its bucket; pass the row quantiser so
    "together" means "on the same PT3 row" — hand-played chords land slightly
    staggered and would never share an exact float onset. Default: exact onset.
    """
    buckets: dict = {}
    for n in notes:
        buckets.setdefault(key(n.start) if key else n.start, []).append(n)
    return [buckets[k] for k in sorted(buckets)]
