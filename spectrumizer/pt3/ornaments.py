"""PT3 ornaments.

An ornament is a per-tick semitone offset list applied on top of a note's pitch,
cycled every frame (50 Hz). Header = [loop_point, length-1] then signed offset
bytes. Cycling a chord's intervals (e.g. 0, +4, +7) at 50 Hz is the classic
AY/Follin trick that fakes a polyphonic chord on a single channel.

Distilled from a hand-written PT3 composer and extended with triad arps.
"""

from __future__ import annotations


def _ornament(offsets: list[int], loop: int = 0) -> bytes:
    out = bytearray()
    out.append(loop & 0xFF)
    out.append(len(offsets) - 1)
    for off in offsets:
        out.append(off & 0xFF)          # signed semitone offset
    return bytes(out)


def build_empty() -> bytes:
    """No-op ornament (single 0 offset)."""
    return bytes([0x00, 0x00, 0x00])


def build_octave() -> bytes:
    """Octave doubling (root, root+12) — stacked-voice power for short notes."""
    return _ornament([0, 12])


def build_major_arp() -> bytes:
    """Major triad arpeggio (root, +4, +7) cycled at frame rate."""
    return _ornament([0, 4, 7])


def build_minor_arp() -> bytes:
    """Minor triad arpeggio (root, +3, +7) cycled at frame rate."""
    return _ornament([0, 3, 7])


# Canonical ornament slot assignment.
ORN_EMPTY, ORN_OCTAVE, ORN_MAJOR, ORN_MINOR = 0, 1, 2, 3

DEFAULT_ORNAMENTS: dict[int, bytes] = {
    ORN_EMPTY: build_empty(),
    ORN_OCTAVE: build_octave(),
    ORN_MAJOR: build_major_arp(),
    ORN_MINOR: build_minor_arp(),
}
