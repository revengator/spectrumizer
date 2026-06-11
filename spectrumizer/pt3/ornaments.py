"""PT3 ornaments.

An ornament is a per-tick semitone offset list applied on top of a note's pitch,
cycled every frame (50 Hz). Header = [loop_point, length-1] then signed offset
bytes. Cycling a chord's intervals (e.g. 0, +4, +7) at 50 Hz is the classic
AY/Follin trick that fakes a polyphonic chord on a single channel.

Distilled from a hand-written PT3 composer and extended with chord arps: the
major/minor triads plus the seventh and suspended qualities, each available at
any step rate (`arp_ornaments(step)` holds every chord tone `step` frames, so
step 1 blurs into a chord and higher steps ripple audibly).
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


# Canonical ornament slot assignment.
(ORN_EMPTY, ORN_OCTAVE, ORN_MAJOR, ORN_MINOR,
 ORN_DOM7, ORN_MAJ7, ORN_MIN7, ORN_SUS2, ORN_SUS4) = range(9)

# Chord-arp ornaments: the semitone intervals each arp cycles over its root.
ARP_INTERVALS: dict[int, tuple[int, ...]] = {
    ORN_MAJOR: (0, 4, 7),
    ORN_MINOR: (0, 3, 7),
    ORN_DOM7: (0, 4, 7, 10),
    ORN_MAJ7: (0, 4, 7, 11),
    ORN_MIN7: (0, 3, 7, 10),
    ORN_SUS2: (0, 2, 7),
    ORN_SUS4: (0, 5, 7),
}


def arp_ornaments(step: int = 1) -> dict[int, bytes]:
    """The chord-arp ornament bank, every chord tone held `step` frames."""
    return {slot: _ornament([i for i in iv for _ in range(step)])
            for slot, iv in ARP_INTERVALS.items()}


DEFAULT_ORNAMENTS: dict[int, bytes] = {
    ORN_EMPTY: build_empty(),
    ORN_OCTAVE: build_octave(),
    **arp_ornaments(),
}
