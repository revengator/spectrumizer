"""Polyphony reduction: many source voices -> at most 3 monophonic AY lines.

`extract_line` peels one monophonic voice off a note set with a high/low
preference (a greedy "skyline"): when two notes overlap, the preferred one wins
and truncates the other. Calling it top-then-bottom-then-top yields lead / bass /
harmony, with everything else dropped.
"""

from __future__ import annotations

import dataclasses

from ..ir import Note


def extract_line(notes: list[Note], prefer: str = 'high'
                 ) -> tuple[list[Note], list[Note]]:
    """Return (line, leftover). `line` is monophonic (non-overlapping)."""
    work = sorted((dataclasses.replace(n) for n in notes),
                  key=lambda n: (n.start, n.pitch))
    line: list[Note] = []
    leftover: list[Note] = []
    for n in work:
        if line and n.start < line[-1].end - 1e-9:
            prev = line[-1]
            better = (n.pitch > prev.pitch) if prefer == 'high' else (n.pitch < prev.pitch)
            if better:
                if n.start - prev.start > 1e-9:
                    prev.dur = n.start - prev.start      # truncate the loser
                    line.append(n)
                else:
                    line.pop(); leftover.append(prev); line.append(n)
            else:
                leftover.append(n)
        else:
            line.append(n)
    return line, leftover


def assign_voices(notes: list[Note], n_pitched: int
                  ) -> tuple[list[Note], list[Note], list[Note]]:
    """Split into (lead, bass, harmony). harmony is empty if n_pitched < 3."""
    lead, rem = extract_line(notes, 'high')
    bass, rem2 = extract_line(rem, 'low')
    harmony: list[Note] = []
    if n_pitched >= 3:
        harmony, _ = extract_line(rem2, 'high')
    return lead, bass, harmony
