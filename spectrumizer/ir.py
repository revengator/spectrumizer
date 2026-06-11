"""Intermediate representation: the source-agnostic model the arranger consumes.

Times are in BEATS (quarter-note units), not ticks or seconds, so input
adapters can normalise resolution independently and the arranger never has to
care where the notes came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Note:
    pitch: int          # MIDI note number 0..127
    start: float        # absolute onset, in beats
    dur: float          # duration, in beats (> 0)
    velocity: int = 96  # 1..127
    track: int = 0      # source track/voice index (hint for voice assignment)

    @property
    def end(self) -> float:
        return self.start + self.dur


@dataclass
class Song:
    """A parsed source piece.

    notes      : pitched notes (everything except the GM drum channel).
    drums      : GM-percussion notes (MIDI channel 10), pitch = GM drum key.
    tempo_bpm  : initial tempo. MVP treats tempo as constant (first set_tempo);
                 adapters should warn if the source has tempo changes.
    """
    notes: list[Note] = field(default_factory=list)
    drums: list[Note] = field(default_factory=list)
    tempo_bpm: float = 120.0
    name: str = ""

    @property
    def length_beats(self) -> float:
        end = 0.0
        for n in self.notes:
            end = max(end, n.end)
        for n in self.drums:
            end = max(end, n.end)
        return end

    @property
    def has_drums(self) -> bool:
        return bool(self.drums)
