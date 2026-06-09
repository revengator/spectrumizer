"""Row-grid model + the bridge to the PT3 channel packer.

A `Placed` note is a pitched/percussive event already quantised to integer rows.
`rasterize` turns a channel's Placed notes into a per-row cell list (REST / OFF /
note / (note, opts)); `pack_patterns` slices the song into fixed-size patterns
and encodes each channel, enforcing the player's two hard invariants (see
pt3.encode): every channel of a pattern encodes exactly ROWS_PER_PATTERN rows,
and row 0 is never a dropped leading rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..pt3 import encode_channel, REST, OFF

ROWS_PER_PATTERN = 64


@dataclass
class Placed:
    start: int                       # start row (inclusive)
    end: int                         # end row (exclusive)
    note: int                        # PT3 note byte
    opts: dict = field(default_factory=dict)   # vol / ornament / sample


def rasterize(placed: list[Placed], total_rows: int) -> list:
    """Channel Placed notes -> per-row cells of length total_rows."""
    cells: list = [REST] * total_rows
    placed = sorted(placed, key=lambda p: p.start)
    for idx, p in enumerate(placed):
        if p.start >= total_rows:
            continue
        cells[p.start] = (p.note, dict(p.opts)) if p.opts else p.note
        nxt = placed[idx + 1].start if idx + 1 < len(placed) else total_rows
        # cut the note (OFF) when there is a real gap before the next onset.
        if p.end < nxt and 0 <= p.end < total_rows and cells[p.end] == REST:
            cells[p.end] = OFF
    return cells


def pack_patterns(specs: list[tuple], total_rows: int,
                  rows_per_pattern: int = ROWS_PER_PATTERN
                  ) -> list[tuple[bytes, bytes, bytes]]:
    """Encode 3 channels into a list of (A, B, C) byte triples.

    specs: 3 tuples (cells, default_sample, default_volume, default_ornament),
    one per AY channel, each `cells` of length total_rows. A held note that
    crosses a pattern boundary is re-attacked at row 0 (pitch continuity);
    genuine silence at row 0 is anchored with OFF so the packer doesn't drop it.
    """
    assert total_rows % rows_per_pattern == 0
    n_pat = total_rows // rows_per_pattern
    last_note: list = [None, None, None]
    patterns: list[tuple[bytes, bytes, bytes]] = []

    for pi in range(n_pat):
        chans: list[bytes] = []
        for ci, (cells, sample, vol, orn) in enumerate(specs):
            sl = list(cells[pi * rows_per_pattern:(pi + 1) * rows_per_pattern])
            if sl and sl[0] == REST:
                sl[0] = last_note[ci] if last_note[ci] is not None else OFF
            for cell in sl:
                if cell == REST:
                    continue
                if cell == OFF:
                    last_note[ci] = None
                else:
                    last_note[ci] = cell[0] if isinstance(cell, tuple) else cell
            chans.append(encode_channel(sl, default_sample=sample,
                                        default_volume=vol, ornament=orn))
        patterns.append((chans[0], chans[1], chans[2]))
    return patterns
