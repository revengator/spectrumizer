"""Chord detection for the arpeggio embellisher.

The arranger reduces polyphony to monophonic lines (`reduce.assign_voices`), so a
source chord normally loses everything but its skyline note. Chord arpeggios buy
that polyphony back on a single channel: identify the triad sounding at an onset,
play its root, and cycle a major/minor ornament (root, +third, +fifth) at 50 Hz
so the one channel implies the whole chord (the classic AY/Follin trick — see
`pt3.ornaments`).

This module only *recognises* triads from a pitch set; building the arp line is
`embellish.chord_arps`.
"""

from __future__ import annotations

from ..ir import Note


def identify_triad(pitches: list[int]) -> tuple[int, str] | None:
    """Recognise a major/minor triad in a set of MIDI pitches.

    Returns (root_pitch_class, 'maj'|'min'), or None if no triad is present
    (fewer than 2 distinct pitch classes, or no major/minor third over any
    candidate root). A root that also carries a perfect fifth outscores a bare
    root+third; ties prefer the root that matches the bass note (root position).
    """
    pcs = sorted({p % 12 for p in pitches})
    if len(pcs) < 2:
        return None
    bass_pc = min(pitches) % 12
    best_key: tuple[int, int] | None = None
    best: tuple[int, str] | None = None
    for root in pcs:
        iv = {(pc - root) % 12 for pc in pcs}
        if 4 in iv:
            quality = 'maj'
        elif 3 in iv:
            quality = 'min'
        else:
            continue
        # full triad (third + fifth) beats a bare third; root==bass breaks ties.
        key = (2 if 7 in iv else 1, 1 if root == bass_pc else 0)
        if best_key is None or key > best_key:
            best_key, best = key, (root, quality)
    return best


def group_by_onset(notes: list[Note]) -> list[list[Note]]:
    """Bucket notes that share a start time (sorted by onset). Exact-match
    grouping: MIDI sources align chord notes to the same tick, and the arranger
    already quantises onsets to the row grid downstream."""
    buckets: dict[float, list[Note]] = {}
    for n in notes:
        buckets.setdefault(n.start, []).append(n)
    return [buckets[k] for k in sorted(buckets)]
