"""Packaging a .pt3 into a self-playing tape / snapshot.

The pure-Python TAP builder is always exercised; the full assemble-with-sjasmplus
path is skipped where sjasmplus is not installed (e.g. CI)."""

import os
import shutil

import pytest

from spectrumizer.pack import _build_tap, pack
from spectrumizer.pt3 import (
    encode_channel, build_pt3, DEFAULT_SAMPLES, DEFAULT_ORNAMENTS, REST, OFF,
)

HAS_SJASM = shutil.which("sjasmplus") is not None


def _tiny_pt3() -> bytes:
    a = encode_channel(['C-4'] + [REST] * 46 + [OFF] + [REST] * 16,
                       default_sample=1, default_volume=15)
    b = encode_channel(['C-3'] + [REST] * 63, default_sample=2, default_volume=14)
    c = encode_channel(['C-5'] + [REST] * 63, default_sample=3, default_volume=10)
    return build_pt3([(a, b, c)], dict(DEFAULT_SAMPLES), dict(DEFAULT_ORNAMENTS),
                     name="TINY")


def _blocks(tap: bytes) -> list:
    out, i = [], 0
    while i < len(tap):
        ln = int.from_bytes(tap[i:i + 2], 'little')
        out.append(tap[i + 2:i + 2 + ln])
        i += 2 + ln
    return out


def test_build_tap_structure():
    img = bytes(range(200))
    blocks = _blocks(_build_tap(img, "demo", org=0x8000))
    assert len(blocks) == 4                              # BASIC hdr+data, CODE hdr+data
    for blk in blocks:                                   # every block checksum is valid
        x = 0
        for byte in blk[:-1]:
            x ^= byte
        assert x == blk[-1]
    assert blocks[2][1] == 3                             # CODE header type
    assert int.from_bytes(blocks[2][14:16], 'little') == 0x8000   # loads at 0x8000
    assert blocks[3][1:-1] == img                        # CODE payload is the image
    for tok in (0xFD, 0xEF, 0xAF, 0xF9, 0xC0):          # CLEAR/LOAD/CODE/RANDOMIZE/USR
        assert tok in blocks[1]


def test_pack_requires_an_output(tmp_path):
    p = tmp_path / "x.pt3"
    p.write_bytes(_tiny_pt3())
    with pytest.raises(ValueError):
        pack(str(p))                                     # neither tap nor sna


def test_pack_rejects_non_pt3(tmp_path):
    p = tmp_path / "x.pt3"
    p.write_bytes(b"NOT A PT3 FILE")
    with pytest.raises(ValueError):
        pack(str(p), tap=str(tmp_path / "o.tap"))


@pytest.mark.skipif(not HAS_SJASM, reason="sjasmplus not installed")
def test_pack_emits_tap_and_sna(tmp_path):
    src = tmp_path / "t.pt3"
    src.write_bytes(_tiny_pt3())
    tap, sna = tmp_path / "t.tap", tmp_path / "t.sna"
    written = pack(str(src), tap=str(tap), sna=str(sna))
    assert {os.path.basename(w) for w in written} == {"t.tap", "t.sna"}
    assert sna.stat().st_size == 131103                  # 128K snapshot
    blocks = _blocks(tap.read_bytes())
    assert len(blocks) == 4 and blocks[2][1] == 3        # valid CODE block
    assert int.from_bytes(blocks[2][14:16], 'little') == 0x8000
    # the loaded image begins with the loader: di / ld sp,nn / ld bc,$7FFD
    image = blocks[3][1:-1]
    assert image[0] == 0xF3 and image[1] == 0x31 and image[4] == 0x01
    # ... and carries the title screen's texts
    for text in (b"spectrumizer", b"github.com/revengator"):
        assert text in image
