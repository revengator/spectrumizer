"""PT3 playback: parse a generated module back and render it to PCM."""

from spectrumizer.pt3 import (
    encode_channel, build_pt3, decode_row_count, NOTE_TO_BYTE,
    DEFAULT_SAMPLES, DEFAULT_ORNAMENTS, REST, OFF,
)
from spectrumizer.pt3.player import parse_module, iter_frames
from spectrumizer import audio

ROWS = 64


def _cells(events):
    """events: {row: note}. Fill a 64-row channel, row 0 must be an event."""
    cells = [REST] * ROWS
    for r, n in events.items():
        cells[r] = n
    return cells


def _make_module(speed=6):
    a = encode_channel(_cells({0: 'C-4', 16: 'E-4', 32: 'G-4', 48: OFF}),
                       default_sample=1, default_volume=15)
    b = encode_channel(_cells({0: 'C-3', 32: 'G-3'}),
                       default_sample=2, default_volume=14)
    c = encode_channel(_cells({0: 'C-5'}),
                       default_sample=3, default_volume=10)
    # every channel of a pattern must encode the same number of rows
    assert decode_row_count(a) == decode_row_count(b) == decode_row_count(c) == ROWS
    pt3 = build_pt3([(a, b, c)], dict(DEFAULT_SAMPLES), dict(DEFAULT_ORNAMENTS),
                    name="TEST", speed=speed)
    return pt3


def test_parse_header_and_order():
    module = parse_module(_make_module(speed=6))
    assert module.speed == 6
    assert module.order == [0]
    assert len(module.patterns) == 1
    assert module.name == "TEST"
    # default sample/ornament slots survive the round-trip
    assert 1 in module.samples and 2 in module.samples
    assert 0 in module.ornaments


def test_decoded_events_match_source():
    module = parse_module(_make_module())
    chA = module.patterns[0][0]
    assert len(chA) == ROWS
    onsets = {r: ev for r, ev in enumerate(chA) if ev is not None}
    assert set(onsets) == {0, 16, 32, 48}
    assert onsets[0].note == NOTE_TO_BYTE['C-4']
    assert onsets[48].note is None            # OFF = note cut


def test_frame_count_matches_speed():
    module = parse_module(_make_module(speed=6))
    frames = list(iter_frames(module))
    assert len(frames) == ROWS * 6            # 64 rows * 6 frames/row
    # each frame is (channels, noise_period) with 3 channels
    assert all(len(f) == 2 and len(f[0]) == 3 for f in frames)


def test_noise_period_is_derived_not_fixed():
    # spectrumizer never emits PD_NOIS and its samples carry byte0 == 0, so the
    # real per-frame noise register is 0 throughout (hardware period 1).
    module = parse_module(_make_module())
    assert all(noise == 0 for _channels, noise in iter_frames(module))


def test_render_is_audible():
    module = parse_module(_make_module())
    pcm, ch = audio.render_pcm(module, sample_rate=8000)
    frames = ROWS * module.speed * (8000 // 50)
    assert ch == 2                                     # stereo (abc) by default
    assert abs(len(pcm) - frames * ch) <= (8000 // 50) * ch
    assert max(abs(v) for v in pcm) > 0               # not silence


def test_max_seconds_caps_length():
    module = parse_module(_make_module())
    pcm, ch = audio.render_pcm(module, sample_rate=8000, max_seconds=1.0)
    assert abs(len(pcm) - 8000 * ch) <= (8000 // 50) * ch


def test_stereo_pans_channels_and_mono_collapses():
    module = parse_module(_make_module())
    st, ch = audio.render_pcm(module, sample_rate=8000, stereo='abc', separation=1.0)
    assert ch == 2
    assert st[0::2] != st[1::2]                        # A (left) != C (right)
    mono, mch = audio.render_pcm(module, sample_rate=8000, stereo='mono')
    assert mch == 1


def test_pt3_tone_table_exact():
    t = audio.build_pt3_table()
    assert len(t) == 96
    assert t[0] == 0x0D10 and t[11] == 0x06EC        # C-1 .. B-1
    assert t[12] == 0x0D10 >> 1                       # C-2 is an octave up
    assert t[95] == 0x06EC >> 7                       # B-8 (top)
    assert all(t[i] >= t[i + 1] for i in range(95))   # never rises in pitch
    assert all(t[i] > t[i + 1] for i in range(84))    # strictly down through oct 7


def test_pt3_close_to_equal_tempered():
    pt3, eq = audio.build_pt3_table(), audio.build_equal_table()
    assert pt3 != eq                                  # a distinct, real table
    assert all(abs(p - e) <= max(2, e * 0.02) for p, e in zip(pt3, eq))
