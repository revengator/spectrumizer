"""PT3 playback: parse a generated module back and render it to PCM."""

import pytest

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
    # each frame is (channels, noise_period, envelope) with 3 channels, and each
    # channel is a 6-tuple (note, amp, tone_on, noise_on, use_env, tone_ofs)
    assert all(len(f) == 3 and len(f[0]) == 3 and len(f[0][0]) == 6 for f in frames)


def test_noise_period_is_derived_not_fixed():
    # spectrumizer never emits PD_NOIS and its MELODIC samples carry byte0 == 0,
    # so the per-frame noise register stays 0 here (hardware period 1). The
    # drum samples DO drive it — see test_drum_samples_drive_the_noise_period.
    module = parse_module(_make_module())
    assert all(noise == 0 for _channels, noise, _env in iter_frames(module))


def test_mid_pattern_sample_change_roundtrips():
    # a channel that switches samples mid-pattern (the drums do: kick<->snare)
    # must decode back to the same slots — the 0xD0+slot token is NOT 0xD0|slot
    from spectrumizer.pt3.player import decode_channel
    c = encode_channel(_cells({0: ('C-4', {'sample': 5}),
                               8: ('C-4', {'sample': 4})}),
                       default_sample=4, default_volume=13)
    rows = decode_channel(c, 0)
    assert rows[0].sample == 5 and rows[8].sample == 4


def test_drum_samples_encode_their_noise_period():
    from spectrumizer.pt3.player import parse_sample
    from spectrumizer.pt3 import samples as smp
    snare = parse_sample(smp.build_snare(), 0)
    # every snare tick is on the noise path at the snare's period
    assert all(t[3] and t[4] == smp.SNARE_NOISE for t in snare.ticks)
    kick = parse_sample(smp.build_kick(), 0)
    assert kick.ticks[0][3] and kick.ticks[0][4] == smp.KICK_NOISE
    assert not kick.ticks[2][3]        # tone-only ticks keep byte0 = 0 (env slide!)


def test_hat_samples_are_bright_noise_bursts():
    from spectrumizer.pt3.player import parse_sample
    from spectrumizer.pt3 import samples as smp
    closed = parse_sample(smp.build_hat(), 0)
    opened = parse_sample(smp.build_hat_open(), 0)
    for hat in (closed, opened):
        # noise-only at the near-maximum brightness, decaying to a silent loop
        assert all(t[3] and t[4] == smp.HAT_NOISE and not t[0] for t in hat.ticks)
        assert hat.ticks[-1][2] == 0 and hat.loop == len(hat.ticks) - 1
    assert len(opened.ticks) > 2 * len(closed.ticks)   # the open hat rings on


def test_drum_samples_drive_the_noise_period():
    from spectrumizer.pt3 import S_SNARE, S_KICK
    from spectrumizer.pt3.samples import SNARE_NOISE, KICK_NOISE
    a = encode_channel(_cells({0: 'C-4'}), default_sample=1, default_volume=15)
    b = encode_channel(_cells({0: 'C-3'}), default_sample=2, default_volume=14)
    c = encode_channel(_cells({0: ('C-4', {'sample': S_KICK}),
                               8: ('C-4', {'sample': S_SNARE})}),
                       default_sample=S_SNARE, default_volume=13)
    pt3 = build_pt3([(a, b, c)], dict(DEFAULT_SAMPLES), dict(DEFAULT_ORNAMENTS),
                    name="DRUMS", speed=6)
    frames = list(iter_frames(parse_module(pt3)))
    # 6 frames per row: the kick thuds dark from row 0, the snare from row 8
    # (channel C is processed last, so the drum wins R6 over the bass attack)
    assert frames[0][1] == KICK_NOISE
    assert frames[8 * 6][1] == SNARE_NOISE


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


# --- AY hardware envelopes (buzzer bass) -------------------------------------

def _bass_module(env=(10, 0x0300), off_row=None):
    """A tiny 3-channel module whose bass (B) optionally uses the AY envelope.

    A = lead (governs pattern length), B = bass, C = a held inner voice. Pass
    `env=(shape, period)` to drive B from the hardware envelope at row 0, and
    `off_row` to turn it back off partway through.
    """
    a = encode_channel(_cells({0: 'C-5', 48: OFF}),
                       default_sample=1, default_volume=15)
    bcells = _cells({0: 'C-3'})
    if env is not None:
        bcells[0] = ('C-3', {'env': env})
    if off_row is not None:
        bcells[off_row] = ('C-3', {'env': 'off'})
    b = encode_channel(bcells, default_sample=2, default_volume=14)
    c = encode_channel(_cells({0: 'E-4'}), default_sample=3, default_volume=10)
    assert decode_row_count(a) == decode_row_count(b) == decode_row_count(c) == ROWS
    return build_pt3([(a, b, c)], dict(DEFAULT_SAMPLES), dict(DEFAULT_ORNAMENTS),
                     name="BASS", speed=6)


def test_envelope_tokens_roundtrip_through_decode():
    module = parse_module(_bass_module(env=(10, 0x0300), off_row=32))
    chB = module.patterns[0][1]
    assert chB[0].env == (10, 0x0300) and chB[0].env_retrig is True
    assert chB[32].env is None and chB[32].env_retrig is True   # 0xB0 -> env OFF
    # the per-pattern row invariant survives the extra (zero-row) env tokens
    assert all(decode_row_count(ch) == ROWS
               for ch in (encode_channel(_cells({0: 'C-3'})),))


def test_iter_frames_reports_envelope_and_retriggers_once():
    frames = list(iter_frames(parse_module(_bass_module(env=(8, 0x0123), off_row=32))))
    assert frames[0][2][:2] == (0x0123, 8)            # envelope = (period, shape)
    assert frames[0][2][2] is True                    # retrigger: row 0, frame 0
    assert all(frames[f][2][2] is False for f in range(1, 6))   # ...only there
    assert frames[0][0][1][4] is True                 # channel B flagged use_env
    # envelope turned off at row 32 (= frame 192): no channel uses it any more
    assert frames[192][2][:2] == (0, 0)
    assert frames[192][0][1][4] is False


def test_envelope_changes_the_rendered_timbre():
    on = parse_module(_bass_module(env=(10, 0x0300)))
    off = parse_module(_bass_module(env=None))
    pon, _ = audio.render_pcm(on, sample_rate=8000)
    poff, _ = audio.render_pcm(off, sample_rate=8000)
    assert max(abs(v) for v in pon) > 0               # audible
    assert list(pon) != list(poff)                    # the envelope reshapes B


def test_envelope_shape_table():
    # repeating triangle (10): down 15..0 then up 0..15, loops from the start
    levels, loop = audio._ENV_SHAPES[10]
    assert levels[:16] == list(range(15, -1, -1))
    assert levels[16:] == list(range(0, 16))
    assert loop == 0 and len(levels) == 32
    # sawtooth up (12): 0..15, loops from the start
    levels, loop = audio._ENV_SHAPES[12]
    assert levels == list(range(16)) and loop == 0
    # one-shot decay (0): 15..0 then hold 0; hold-high (11): decay then hold 15
    levels, loop = audio._ENV_SHAPES[0]
    assert levels[:16] == list(range(15, -1, -1)) and levels[loop] == 0
    levels, loop = audio._ENV_SHAPES[11]
    assert levels[loop] == 15


def test_envelope_shape_out_of_range_rejected():
    for bad in (0, 15, 16):                            # 0->NtSkip, 15->OFF token
        with pytest.raises(ValueError):
            encode_channel([('C-3', {'env': (bad, 0x0100)})])


def test_mixer_negative_logic_matches_real_player():
    from spectrumizer.pt3.player import _mixer
    assert _mixer(0x80) == (True, False)               # tone only
    assert _mixer(0x10) == (False, True)               # noise only
    assert _mixer(0x00) == (True, True)                # tone + noise
    assert _mixer(0x90) == (False, False)              # buzzer: envelope only


def test_envelope_period_for_pitch():
    from spectrumizer.pt3 import envelope_period_for, envelope_steps
    assert envelope_steps(10) == 32 and envelope_steps(8) == 16   # triangle vs saw
    assert envelope_period_for(0x0D10, 10) == round(0x0D10 / 512)  # EP = P/(16*N)
    assert envelope_period_for(64, 10) >= 1                        # never below 1
    # a deeper note (larger tone period) maps to a larger envelope period
    assert envelope_period_for(3344, 10) > envelope_period_for(836, 10)


def test_vibrato_sample_encodes_tone_offsets():
    from spectrumizer.pt3.player import parse_sample
    from spectrumizer.pt3 import samples as smp
    vib = parse_sample(smp.build_lead_vibrato(), 0)
    assert vib.loop == 8
    assert [t[6] for t in vib.ticks[:8]] == [0] * 8            # steady attack
    assert [t[6] for t in vib.ticks[8:]] == [0, 2, 3, 2, 0, -2, -3, -2]
    assert not any(t[7] for t in vib.ticks)                    # no TnAcc use


def test_vibrato_wobbles_the_tone_period():
    from spectrumizer.pt3 import S_LEAD_VIB
    a = encode_channel(_cells({0: 'A-4'}), default_sample=S_LEAD_VIB,
                       default_volume=15)
    b = encode_channel(_cells({0: 'C-3'}), default_sample=2, default_volume=14)
    c = encode_channel(_cells({0: 'C-5'}), default_sample=3, default_volume=10)
    pt3 = build_pt3([(a, b, c)], dict(DEFAULT_SAMPLES), dict(DEFAULT_ORNAMENTS),
                    name="VIB", speed=6)
    frames = list(iter_frames(parse_module(pt3)))
    offs = [fr[0][0][5] for fr in frames[:24]]    # channel A tone_ofs per tick
    assert offs[:8] == [0] * 8                    # delayed: the attack is steady
    assert offs[8:16] == [0, 2, 3, 2, 0, -2, -3, -2]   # one triangle cycle
    assert offs[16:24] == offs[8:16]              # ... that loops


def test_volume_zero_or_overflow_is_rejected():
    # 0xC0|0 IS the OFF token (and 16+ would wrap back into it): vol is 1..15,
    # silence is an OFF cell, never a volume.
    with pytest.raises(ValueError):
        encode_channel(_cells({0: ('C-4', {'vol': 0})}))
    with pytest.raises(ValueError):
        encode_channel(_cells({0: ('C-4', {'vol': 16})}))
    with pytest.raises(ValueError):
        encode_channel(_cells({0: 'C-4'}), default_volume=0)


def test_foreign_modules_are_flagged_not_silent():
    # a hand-built channel with a token spectrumizer never emits (0x05, a
    # Vortex pattern command): the parser reports it instead of just skipping
    foreign = bytes([0xC5, 0xB1, 0x40, 0x05, 0x50, 0x00])  # vol, skip 64, ?, C-1
    pt3 = build_pt3([(foreign, foreign, foreign)], dict(DEFAULT_SAMPLES),
                    dict(DEFAULT_ORNAMENTS), name="FOREIGN", tone_table=2)
    module = parse_module(pt3)
    assert module.unknown_tokens == frozenset({0x05})
    assert module.tone_table == 2
    # ... and a spectrumizer-generated module is clean
    own = parse_module(_make_module())
    assert own.unknown_tokens == frozenset()
    assert own.tone_table == 1


def test_vortex_tracker_signature_is_accepted():
    # Vortex Tracker writes the same fixed-offset header under its own banner
    # (both are exactly 30 bytes; the real player never reads the text)
    pt3 = bytearray(_make_module(speed=6))
    pt3[:30] = b'Vortex Tracker II 1.0 module: '
    module = parse_module(bytes(pt3))
    assert module.speed == 6 and module.order == [0]
    with pytest.raises(ValueError):
        parse_module(b'not a module' + bytes(300))


def test_truncated_modules_never_crash_the_parser():
    # foreign/corrupt modules may cut samples, ornaments, operands or the
    # pattern table short: the parser clamps to EOF instead of IndexError-ing
    pt3 = _make_module()
    for cut in range(0xC9, len(pt3)):
        parse_module(pt3[:cut])
