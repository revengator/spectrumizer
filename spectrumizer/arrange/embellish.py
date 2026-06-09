"""Chiptune embellishers (only run for --style chiptune).

MVP passes:
  * octave_short_lead — octave-double SHORT lead notes (the classic AY brightener;
    held notes stay single-voice so they don't warble).
  * synth_drums       — a backbeat (kick on beats 1&3, snare on 2&4) when the
    source has no drum track, so chiptune output still has percussive drive.

Planned next: chord arpeggios via ORN_MAJOR/ORN_MINOR (the ornament builders are
already wired in pt3.ornaments) to fake polyphony on a single channel.
"""

from __future__ import annotations

from .model import Placed
from ..pt3 import ORN_OCTAVE, ORN_EMPTY


def octave_short_lead(lead: list[Placed], short_thresh_rows: int) -> None:
    """In place: octave ornament on notes shorter than the threshold."""
    for p in lead:
        p.opts['ornament'] = ORN_OCTAVE if (p.end - p.start) < short_thresh_rows else ORN_EMPTY


def synth_drums(total_rows: int, rows_per_beat: int, drum_byte: int,
                snare_sample: int, kick_sample: int) -> list[Placed]:
    """A simple 4/4 backbeat occupying one channel (drums = noise, tone off)."""
    placed: list[Placed] = []
    n_beats = total_rows // rows_per_beat
    for b in range(n_beats):
        row = b * rows_per_beat
        if row >= total_rows:
            break
        if b % 4 in (0, 2):
            placed.append(Placed(row, row + 1, drum_byte, {'sample': kick_sample}))
        else:
            placed.append(Placed(row, row + 1, drum_byte, {'sample': snare_sample}))
    return placed
