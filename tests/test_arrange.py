"""Arranger end-to-end: reduction, the PT3 channel-length invariant, styles."""

from spectrumizer.ir import Song, Note
from spectrumizer.arrange import arrange, vol_from_velocity
from spectrumizer.arrange.reduce import assign_voices
from spectrumizer.arrange.model import ROWS_PER_PATTERN
from spectrumizer.pt3 import decode_row_count
from spectrumizer.pt3.player import parse_module


def _chord_song():
    # A repeated C-E-G triad (3 simultaneous voices) over 8 beats, plus a low bass.
    notes = []
    for beat in range(8):
        notes.append(Note(pitch=72, start=beat, dur=1))   # top  (lead)
        notes.append(Note(pitch=67, start=beat, dur=1))   # mid  (harmony)
        notes.append(Note(pitch=48, start=beat, dur=1))   # low  (bass)
    return Song(notes=notes, tempo_bpm=120.0, name="TRIAD")


def test_assign_voices_skyline():
    song = _chord_song()
    lead, bass, harmony = assign_voices(song.notes, n_pitched=3)
    assert all(n.pitch == 72 for n in lead)
    assert all(n.pitch == 48 for n in bass)
    assert all(n.pitch == 67 for n in harmony)


def _pattern_channel_addrs(pt3, n_patterns):
    ppt = pt3[0x67] | (pt3[0x68] << 8)
    out = []
    for p in range(n_patterns):
        base = ppt + p * 6
        a = pt3[base] | (pt3[base + 1] << 8)
        b = pt3[base + 2] | (pt3[base + 3] << 8)
        c = pt3[base + 4] | (pt3[base + 5] << 8)
        out.append((a, b, c))
    return out


def test_row_invariant_faithful():
    pt3, stats = arrange(_chord_song(), style='faithful')
    assert stats['total_rows'] % ROWS_PER_PATTERN == 0
    for (a, b, c) in _pattern_channel_addrs(pt3, stats['patterns']):
        for addr in (a, b, c):
            assert decode_row_count(pt3[addr:]) == ROWS_PER_PATTERN


def test_row_invariant_chiptune_and_styles_differ():
    song = _chord_song()
    faithful, sf = arrange(song, style='faithful')
    chiptune, sc = arrange(song, style='chiptune')

    for (a, b, c) in _pattern_channel_addrs(chiptune, sc['patterns']):
        for addr in (a, b, c):
            assert decode_row_count(chiptune[addr:]) == ROWS_PER_PATTERN

    # chiptune drops harmony for synth drums; faithful keeps harmony
    assert sf['voices']['channel_c'] == 'harmony'
    assert sc['voices']['channel_c'] == 'synth-drums'
    assert faithful != chiptune


def test_drums_take_channel_c():
    song = _chord_song()
    song.drums = [Note(pitch=36, start=b, dur=0.25) for b in range(8)]
    _, stats = arrange(song, style='faithful')
    assert stats['voices']['channel_c'] == 'drums'
    assert stats['voices']['drums'] == 8


def test_valid_pt3_header():
    pt3, _ = arrange(_chord_song(), style='faithful')
    assert pt3[0x00:0x0D] == b'ProTracker 3.'


def _dyn_song():
    # one lead voice alternating loud/soft so velocity must drive the volume
    notes = [Note(pitch=72, start=b, dur=1, velocity=(120 if b % 2 == 0 else 30))
             for b in range(8)]
    return Song(notes=notes, tempo_bpm=120.0, name="DYN")


def test_vol_from_velocity():
    assert vol_from_velocity(127, 15, 127) == 15      # loudest note -> ceiling
    assert vol_from_velocity(64, 15, 127) == 8
    assert vol_from_velocity(1, 15, 127) == 1         # floor: never fully silent
    assert vol_from_velocity(96, 10, 96) == 10        # piece max -> channel ceiling
    assert vol_from_velocity(50, 13, 0) == 13         # vmax<=0 -> dynamics off


def _lead_volumes(pt3):
    m = parse_module(pt3)
    return {ev.vol for ch in m.patterns[0] for ev in ch
            if ev is not None and ev.note is not None}


def test_dynamics_vary_volume():
    pt3, stats = arrange(_dyn_song(), style='faithful', dynamics=True)
    assert stats['dynamics'] is True
    assert len(_lead_volumes(pt3)) >= 2               # velocity -> different volumes


def test_no_dynamics_is_flat():
    pt3, stats = arrange(_dyn_song(), style='faithful', dynamics=False)
    assert stats['dynamics'] is False
    assert len(_lead_volumes(pt3)) == 1               # single flat volume


def _bass_events(pt3):
    m = parse_module(pt3)
    return [ev for ev in m.patterns[0][1] if ev is not None and ev.note is not None]


def test_buzzer_bass_modes_emit_envelope_and_keep_invariant():
    song = _chord_song()                              # bass = MIDI 48 (C-3)
    for mode, sample in (('envelope', 6), ('envelope-tone', 7)):
        pt3, stats = arrange(song, style='faithful', bass=mode)
        assert stats['bass'] == mode
        # the per-pattern row invariant survives the extra (zero-row) env tokens
        for (a, b, c) in _pattern_channel_addrs(pt3, stats['patterns']):
            for addr in (a, b, c):
                assert decode_row_count(pt3[addr:]) == ROWS_PER_PATTERN
        bass_evs = _bass_events(pt3)
        assert bass_evs and all(ev.sample == sample for ev in bass_evs)
        # every bass note carries a shape-10 envelope at a real (>=1) period
        assert all(ev.env and ev.env[0] == 10 and ev.env[1] >= 1 for ev in bass_evs)


def test_normal_bass_has_no_envelope():
    pt3, stats = arrange(_chord_song(), style='faithful', bass='normal')
    assert stats['bass'] == 'normal'
    bass_evs = _bass_events(pt3)
    assert bass_evs and all(ev.env is None and ev.sample == 2 for ev in bass_evs)


def _triad_song():
    # a full C-major triad (C E G) restruck every beat, over a low C bass
    notes = []
    for beat in range(8):
        for pitch in (72, 76, 79):                # C5 E5 G5 -> root C, major
            notes.append(Note(pitch=pitch, start=beat, dur=1))
        notes.append(Note(pitch=48, start=beat, dur=1))   # C3 bass
    return Song(notes=notes, tempo_bpm=120.0, name="CMAJ")


def _channel_c_ornaments(pt3):
    m = parse_module(pt3)
    return {ev.ornament for ev in m.patterns[0][2]
            if ev is not None and ev.note is not None}


def test_arps_put_chord_ornament_on_channel_c():
    from spectrumizer.pt3 import ORN_MAJOR
    pt3, stats = arrange(_triad_song(), style='faithful', arps=True)
    assert stats['arps'] is True
    assert stats['voices']['channel_c'] == 'arp'
    assert stats['voices']['arp'] > 0
    # channel C carries the major-arp ornament (faking the triad on one channel)
    assert ORN_MAJOR in _channel_c_ornaments(pt3)
    # the row invariant must still hold with the extra ornament tokens
    for (a, b, c) in _pattern_channel_addrs(pt3, stats['patterns']):
        for addr in (a, b, c):
            assert decode_row_count(pt3[addr:]) == ROWS_PER_PATTERN


def test_arps_off_keeps_plain_harmony():
    from spectrumizer.pt3 import ORN_EMPTY
    pt3, stats = arrange(_triad_song(), style='faithful', arps=False)
    assert stats['voices']['channel_c'] == 'harmony'
    assert _channel_c_ornaments(pt3) == {ORN_EMPTY}


def test_real_drums_outrank_arps_on_channel_c():
    song = _triad_song()
    song.drums = [Note(pitch=36, start=b, dur=0.25) for b in range(8)]
    _, stats = arrange(song, style='chiptune', arps=True)
    assert stats['voices']['channel_c'] == 'drums'   # drums win over arps


def test_arps_recognise_humanised_chords():
    # the triad's notes land a few hundredths of a beat apart (hand-played):
    # they still quantise to the same row, so the arp must still engage
    from spectrumizer.pt3 import ORN_MAJOR
    notes = []
    for beat in range(8):
        for i, pitch in enumerate((72, 76, 79)):
            notes.append(Note(pitch=pitch, start=beat + i * 0.02, dur=1))
    pt3, _ = arrange(Song(notes=notes, tempo_bpm=120.0, name="HUMAN"),
                     style='faithful', arps=True)
    assert ORN_MAJOR in _channel_c_ornaments(pt3)


def test_pattern_boundary_reattack_keeps_volume():
    # a loud anchor, then a soft note held across the 64-row pattern boundary:
    # the row-0 re-attack must keep the note's volume, not jump to the default
    notes = [Note(pitch=72, start=0, dur=1, velocity=120),
             Note(pitch=76, start=1, dur=30, velocity=30)]
    pt3, stats = arrange(Song(notes=notes, tempo_bpm=120.0, name="HOLD"),
                         style='faithful', dynamics=True)
    assert stats['patterns'] >= 2
    m = parse_module(pt3)
    a0 = [ev for ev in m.patterns[0][0] if ev is not None and ev.note is not None]
    held_attack = a0[-1]                    # the soft note's original attack
    reattack = m.patterns[1][0][0]          # its re-attack at the next pattern
    assert reattack is not None and reattack.note == held_attack.note
    assert reattack.vol == held_attack.vol


def test_pattern_boundary_reattack_keeps_arp_ornament():
    # a triad held across the boundary must keep its arp ornament on channel C
    from spectrumizer.pt3 import ORN_MAJOR
    notes = [Note(pitch=p, start=0, dur=20) for p in (72, 76, 79)]
    notes.append(Note(pitch=48, start=0, dur=20))
    pt3, stats = arrange(Song(notes=notes, tempo_bpm=120.0, name="HOLDARP"),
                         style='faithful', arps=True)
    assert stats['patterns'] >= 2
    reattack = parse_module(pt3).patterns[1][2][0]
    assert reattack is not None and reattack.ornament == ORN_MAJOR
