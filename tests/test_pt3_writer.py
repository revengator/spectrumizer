"""PT3 emitter: note mapping, channel packer golden, and header layout."""

from spectrumizer.pt3 import (
    NOTE_TO_BYTE, REST, OFF, midi_to_pt3_byte,
    encode_channel, decode_row_count, build_pt3, HEADER_SIZE,
)


def test_note_table_endpoints():
    assert NOTE_TO_BYTE['C-1'] == 0x50
    assert NOTE_TO_BYTE['B-8'] == 0xAF
    assert NOTE_TO_BYTE['C-4'] == 0x74


def test_midi_to_pt3_byte():
    assert midi_to_pt3_byte(60) == NOTE_TO_BYTE['C-4']      # middle C -> C-4
    # folding keeps everything in range
    assert 0x50 <= midi_to_pt3_byte(0) <= 0xAF
    assert 0x50 <= midi_to_pt3_byte(127) <= 0xAF
    # transpose shifts by semitones
    assert midi_to_pt3_byte(60, transpose=12) == midi_to_pt3_byte(72)


def test_encode_channel_golden():
    # A C-4 held for 2 rows, default sample 1 / volume 15 / ornament 0.
    data = encode_channel(['C-4', REST], default_sample=1,
                          default_volume=15, ornament=0)
    assert data == bytes([0xCF, 0xB1, 0x02, 0xF0, 0x02, 0x74, 0x00])


def test_encode_channel_row_count():
    assert decode_row_count(encode_channel(['C-4'] + [REST] * 63)) == 64
    assert decode_row_count(encode_channel([OFF] + [REST] * 63)) == 64
    rows = ['C-4', REST, OFF, REST, 'E-4'] + [REST] * 59   # 64 rows
    assert decode_row_count(encode_channel(rows)) == 64


def test_build_pt3_header():
    ch = encode_channel(['C-4'] + [REST] * 63)
    empty = encode_channel([OFF] + [REST] * 63)
    samples = {1: bytes([0, 0, 0x00, 0x8F, 0x00, 0x00])}
    ornaments = {0: bytes([0x00, 0x00, 0x00])}
    pt3 = build_pt3([(ch, empty, empty)], samples, ornaments,
                    name="TEST", author="ME", speed=6, loop_pos=0)

    assert pt3[0x00:0x0D] == b'ProTracker 3.'
    assert pt3[0x64] == 6                      # speed
    assert pt3[0x66] == 0                      # loop position
    # position list lives at 0xC9 and is terminated by 0xFF
    assert pt3[HEADER_SIZE] == 0               # pattern 0 -> 0*3
    assert pt3[HEADER_SIZE + 1] == 0xFF
    assert pt3[0x65] == 2                       # #positions + terminator
    # sample slot 1 address is non-zero and points inside the file
    addr = pt3[0x6B] | (pt3[0x6C] << 8)
    assert 0 < addr < len(pt3)
