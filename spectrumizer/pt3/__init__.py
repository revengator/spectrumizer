"""PT3 emitter — the proven byte format extracted from the hand-composers.

Produces modules that load in Sergey Bulba's PT3 / Vortex Tracker replayer."""

from .encode import (
    NOTE_TO_BYTE, REST, OFF,
    PT3_NOTE_MIN, PT3_NOTE_MAX,
    midi_to_pt3_byte, encode_channel, decode_row_count,
    envelope_steps, envelope_period_for,
)
from .samples import (
    DEFAULT_SAMPLES, S_LEAD, S_BASS, S_HARMONY, S_SNARE, S_KICK,
    S_BUZZER, S_BUZZER_TONE, S_LEAD_VIB, S_HAT, S_HAT_OPEN,
)
from .ornaments import (
    DEFAULT_ORNAMENTS, ORN_EMPTY, ORN_OCTAVE, ORN_MAJOR, ORN_MINOR,
    ORN_DOM7, ORN_MAJ7, ORN_MIN7, ORN_SUS2, ORN_SUS4, arp_ornaments,
)
from .writer import build_pt3, HEADER_SIZE

__all__ = [
    "NOTE_TO_BYTE", "REST", "OFF", "PT3_NOTE_MIN", "PT3_NOTE_MAX",
    "midi_to_pt3_byte", "encode_channel", "decode_row_count",
    "envelope_steps", "envelope_period_for",
    "DEFAULT_SAMPLES", "S_LEAD", "S_BASS", "S_HARMONY", "S_SNARE", "S_KICK",
    "S_BUZZER", "S_BUZZER_TONE", "S_LEAD_VIB", "S_HAT", "S_HAT_OPEN",
    "DEFAULT_ORNAMENTS", "ORN_EMPTY", "ORN_OCTAVE", "ORN_MAJOR", "ORN_MINOR",
    "ORN_DOM7", "ORN_MAJ7", "ORN_MIN7", "ORN_SUS2", "ORN_SUS4", "arp_ornaments",
    "build_pt3", "HEADER_SIZE",
]
