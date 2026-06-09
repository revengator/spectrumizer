"""PT3 file assembler.

Generalised from a hand-written `build_pt3`. Layout (offsets confirmed against
the PT3 player's INIT routine):

  0x00  13  "ProTracker 3."
  0x0D   1  version char ('5')
  0x0E  16  " compilation of "
  0x1E  32  title
  0x3E   4  " by "
  0x42  32  author
  0x62   1  unused (0x20)
  0x63   1  tone-table id  (1 == the table the bundled player ships with)
  0x64   1  speed (frames per row)            <- player reads this
  0x65   1  position-list length incl. 0xFF   <- player IGNORES this (cosmetic)
  0x66   1  loop position (0-based index into the order)  <- player reads this
  0x67   2  offset to the pattern-pointer table
  0x69  64  32 sample addresses  (2 bytes LE each, 0 = unused)
  0xA9  32  16 ornament addresses
  0xC9 ...  position list (each = pattern_index*3), terminated 0xFF
            pattern-pointer table (6 bytes/pattern: A,B,C addresses, 2B LE)
            pattern bodies, then sample blob, then ornament blob

The player drives pattern length entirely from channel A's 0x00 terminator, so
every channel of a pattern must encode the same number of rows (enforced upstream
in arrange/). See pt3.encode for the channel-length invariant.
"""

from __future__ import annotations

HEADER_SIZE = 0xC9


def _ascii32(s: str) -> bytes:
    return s.encode('ascii', 'replace')[:32].ljust(32, b' ')


def build_pt3(patterns: list[tuple[bytes, bytes, bytes]],
              samples: dict[int, bytes],
              ornaments: dict[int, bytes],
              *,
              name: str = "",
              author: str = "SPECTRUMIZER",
              speed: int = 6,
              order: list[int] | None = None,
              loop_pos: int = 0,
              tone_table: int = 1) -> bytes:
    """Assemble a PT3 module.

    patterns  : list of (chanA, chanB, chanC) encoded-byte triples.
    samples   : {slot(1..31): bytes}.   ornaments: {slot(0..15): bytes}.
    order     : the position list as pattern indices (default 0..N-1, each once).
    loop_pos  : 0-based index into `order` to jump to after the song ends.
    """
    if order is None:
        order = list(range(len(patterns)))

    position_list = bytes([p * 3 for p in order] + [0xFF])

    pos_list_offset = HEADER_SIZE
    pat_ptr_table_offset = pos_list_offset + len(position_list)
    pat_ptr_table_size = 6 * len(patterns)
    pat_bodies_offset = pat_ptr_table_offset + pat_ptr_table_size

    cursor = pat_bodies_offset
    pat_addrs: list[tuple[int, int, int]] = []
    pat_bodies = bytearray()
    for (a, b, c) in patterns:
        a_addr = cursor; pat_bodies.extend(a); cursor += len(a)
        b_addr = cursor; pat_bodies.extend(b); cursor += len(b)
        c_addr = cursor; pat_bodies.extend(c); cursor += len(c)
        pat_addrs.append((a_addr, b_addr, c_addr))

    sample_addr: dict[int, int] = {}
    sample_blob = bytearray()
    for idx in sorted(samples):
        sample_addr[idx] = cursor
        sample_blob.extend(samples[idx]); cursor += len(samples[idx])

    ornament_addr: dict[int, int] = {}
    orn_blob = bytearray()
    for idx in sorted(ornaments):
        ornament_addr[idx] = cursor
        orn_blob.extend(ornaments[idx]); cursor += len(ornaments[idx])

    h = bytearray(HEADER_SIZE)
    h[0x00:0x0D] = b'ProTracker 3.'
    h[0x0D] = ord('5')
    h[0x0E:0x1E] = b' compilation of '
    h[0x1E:0x3E] = _ascii32(name)
    h[0x3E:0x42] = b' by '
    h[0x42:0x62] = _ascii32(author)
    h[0x62] = 0x20
    h[0x63] = tone_table & 0xFF
    h[0x64] = speed & 0xFF
    h[0x65] = (len(position_list)) & 0xFF        # = #positions + 1 (incl. 0xFF)
    h[0x66] = loop_pos & 0xFF
    h[0x67:0x69] = pat_ptr_table_offset.to_bytes(2, 'little')
    for i in range(32):
        addr = sample_addr.get(i, 0)
        h[0x69 + i * 2: 0x6B + i * 2] = addr.to_bytes(2, 'little')
    for i in range(16):
        addr = ornament_addr.get(i, 0)
        h[0xA9 + i * 2: 0xAB + i * 2] = addr.to_bytes(2, 'little')

    ppt = bytearray()
    for (a_addr, b_addr, c_addr) in pat_addrs:
        ppt += a_addr.to_bytes(2, 'little')
        ppt += b_addr.to_bytes(2, 'little')
        ppt += c_addr.to_bytes(2, 'little')

    return bytes(h) + position_list + bytes(ppt) + bytes(pat_bodies) + \
        bytes(sample_blob) + bytes(orn_blob)
