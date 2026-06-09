"""Time -> PT3 row grid.

PT3 has no tempo field beyond `speed` (frames per row). At the Spectrum's 50 Hz
interrupt, rows/sec = bpm*rows_per_beat/60, so frames/row = 3000/(bpm*rpb).
"""

from __future__ import annotations

import math

from ..ir import Song
from .model import ROWS_PER_PATTERN


def plan_grid(song: Song, rows_per_beat: int = 4, speed: int | None = None,
              rows_per_pattern: int = ROWS_PER_PATTERN) -> tuple[int, int]:
    """Return (speed, total_rows). total_rows is rounded up to a whole number
    of patterns."""
    bpm = song.tempo_bpm or 120.0
    if speed is None:
        speed = round(3000.0 / (bpm * rows_per_beat))
        speed = max(1, min(31, speed))

    rows = math.ceil(song.length_beats * rows_per_beat)
    rows = max(rows, rows_per_pattern)
    rows = ((rows + rows_per_pattern - 1) // rows_per_pattern) * rows_per_pattern
    return speed, rows


def note_rows(start_beat: float, end_beat: float, rows_per_beat: int,
              total_rows: int) -> tuple[int, int]:
    s = round(start_beat * rows_per_beat)
    e = round(end_beat * rows_per_beat)
    s = max(0, min(total_rows - 1, s))
    e = max(s + 1, min(total_rows, e))
    return s, e
