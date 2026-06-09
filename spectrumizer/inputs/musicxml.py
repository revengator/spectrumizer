"""MusicXML -> IR adapter — DEFERRED (stub).

Planned: parse scores (.musicxml / .mxl) with `music21`, flatten parts/voices to
spectrumizer.ir.Note (pitch from .pitch.midi, start/dur from offsets in
quarter-lengths, which are already beats), tempo from the first MetronomeMark.
This keeps the same IR the MIDI adapter produces, so arrange/ and pt3/ are reused
unchanged.

Add `music21` to requirements.txt when implementing.
"""

from __future__ import annotations

from ..ir import Song


def load_musicxml(path: str) -> Song:
    raise NotImplementedError(
        "MusicXML input is not implemented yet (planned via music21). "
        "Use a MIDI export of the score for now, or export the part to .mid."
    )
