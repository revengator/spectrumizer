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
    assert stats['voices']['channel_c'] == 'drums+harmony'
    assert stats['voices']['drums'] == 8
    assert stats['voices']['harmony'] > 0      # multiplexed, not dropped


def test_drums_multiplex_harmony_on_channel_c():
    from spectrumizer.pt3 import S_KICK, S_HARMONY
    song = _chord_song()                       # lead 72 / harmony 67 / bass 48
    song.drums = [Note(pitch=36, start=b, dur=0.25) for b in range(8)]
    pt3, stats = arrange(song, style='faithful', dynamics=False)
    onsets = {r: ev for r, ev in enumerate(parse_module(pt3).patterns[0][2])
              if ev is not None and ev.note is not None}
    for b in range(8):
        # the kick keeps its row, the harmony re-attacks right after the hit,
        # each with its own sample and volume
        assert onsets[b * 4].sample == S_KICK and onsets[b * 4].vol == 13
        assert onsets[b * 4 + 1].sample == S_HARMONY and onsets[b * 4 + 1].vol == 10
    for (a, b_, c) in _pattern_channel_addrs(pt3, stats['patterns']):
        for addr in (a, b_, c):
            assert decode_row_count(pt3[addr:]) == ROWS_PER_PATTERN


def test_gm_cymbals_map_to_hat_samples():
    from spectrumizer.pt3 import S_KICK, S_SNARE, S_HAT, S_HAT_OPEN
    song = _chord_song()
    # one GM key per beat: kick, snare, closed hat, open hat (twice around)
    keys = [36, 38, 42, 46]
    song.drums = [Note(pitch=keys[b % 4], start=b, dur=0.25) for b in range(8)]
    pt3, _ = arrange(song, style='faithful', dynamics=False)
    onsets = {r: ev for r, ev in enumerate(parse_module(pt3).patterns[0][2])
              if ev is not None and ev.note is not None}
    expected = [(S_KICK, 13), (S_SNARE, 13), (S_HAT, 10), (S_HAT_OPEN, 11)]
    for b in range(8):
        sample, ceil = expected[b % 4]
        # cymbals run quieter than the kick/snare even with dynamics off
        assert onsets[b * 4].sample == sample and onsets[b * 4].vol == ceil


def test_simultaneous_drum_hits_collapse_by_rank():
    from spectrumizer.pt3 import S_KICK
    song = _chord_song()
    # a closed hat, a kick and an open hat all on the same tick: kick wins
    song.drums = [Note(pitch=p, start=0, dur=0.25) for p in (42, 36, 46)]
    pt3, _ = arrange(song, style='faithful', dynamics=False)
    onsets = [ev for ev in parse_module(pt3).patterns[0][2]
              if ev is not None and ev.note is not None]
    assert onsets[0].sample == S_KICK


def test_synth_drums_add_offbeat_hats():
    from spectrumizer.pt3 import S_KICK, S_SNARE, S_HAT, S_HAT_OPEN
    pt3, stats = arrange(_chord_song(), style='chiptune')
    assert stats['voices']['channel_c'] == 'synth-drums'
    onsets = {r: ev for r, ev in enumerate(parse_module(pt3).patterns[0][2])
              if ev is not None and ev.note is not None}
    # one bar at rpb=4: kick/snare on the beats, hats on the off-eighths,
    # the bar's last hat open — and the hats quieter than the backbeat
    bar = [(0, S_KICK), (2, S_HAT), (4, S_SNARE), (6, S_HAT),
           (8, S_KICK), (10, S_HAT), (12, S_SNARE), (14, S_HAT_OPEN)]
    for row, sample in bar:
        assert onsets[row].sample == sample
        assert onsets[row].vol == (13 if sample in (S_KICK, S_SNARE) else
                                   10 if sample == S_HAT_OPEN else 9)


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


def test_arps_recognise_sevenths_and_sus():
    from spectrumizer.pt3 import ORN_MIN7, ORN_SUS4
    notes = []
    for beat in range(4):                         # Am7: A2 + A3 C4 E4 G4
        for pitch in (45, 57, 60, 64, 67):
            notes.append(Note(pitch=pitch, start=beat, dur=1))
    for beat in range(4, 8):                      # Gsus4: G2 + G3 C4 D4
        for pitch in (43, 55, 60, 62):
            notes.append(Note(pitch=pitch, start=beat, dur=1))
    pt3, _ = arrange(Song(notes=notes, tempo_bpm=120.0, name="SEV"), arps=True)
    orns = _channel_c_ornaments(pt3)
    assert ORN_MIN7 in orns and ORN_SUS4 in orns


def test_arp_speed_stretches_the_arp_ornaments():
    from spectrumizer.pt3 import ORN_MAJOR, ORN_OCTAVE
    fast, sf = arrange(_triad_song(), arps=True)
    slow, ss = arrange(_triad_song(), arps=True, arp_speed=3)
    assert sf['arp_speed'] == 1 and ss['arp_speed'] == 3
    assert parse_module(fast).ornaments[ORN_MAJOR].offsets == [0, 4, 7]
    assert parse_module(slow).ornaments[ORN_MAJOR].offsets == \
        [0, 0, 0, 4, 4, 4, 7, 7, 7]
    # only the chord arps slow down — the octave ornament keeps its rate
    assert parse_module(slow).ornaments[ORN_OCTAVE].offsets == [0, 12]


def test_arps_off_keeps_plain_harmony():
    from spectrumizer.pt3 import ORN_EMPTY
    pt3, stats = arrange(_triad_song(), style='faithful', arps=False)
    assert stats['voices']['channel_c'] == 'harmony'
    assert _channel_c_ornaments(pt3) == {ORN_EMPTY}


def test_real_drums_outrank_arps_on_channel_c():
    song = _triad_song()
    song.drums = [Note(pitch=36, start=b, dur=0.25) for b in range(8)]
    _, stats = arrange(song, style='chiptune', arps=True)
    # drums win over arps (the harmony multiplexes into their gaps)
    assert stats['voices']['channel_c'].startswith('drums')


def test_identical_patterns_are_deduplicated():
    # 32 beats of the same one-beat figure = 128 rows = two byte-identical
    # 64-row patterns: stored once, played twice through the position list
    notes = []
    for beat in range(32):
        notes.append(Note(pitch=72, start=beat, dur=0.5))
        notes.append(Note(pitch=48, start=beat, dur=1))
    pt3, stats = arrange(Song(notes=notes, tempo_bpm=120.0, name="LOOP"),
                         style='faithful')
    assert stats['positions'] == 2 and stats['patterns'] == 1
    m = parse_module(pt3)
    assert m.order == [0, 0]
    assert len(m.patterns) == 1
    # ...and total playback length is still both positions
    assert stats['total_rows'] == 2 * ROWS_PER_PATTERN


def test_different_patterns_are_not_deduplicated():
    # the same figure but with a changed second half: two distinct patterns
    notes = []
    for beat in range(32):
        notes.append(Note(pitch=(72 if beat < 16 else 74), start=beat, dur=0.5))
        notes.append(Note(pitch=48, start=beat, dur=1))
    pt3, stats = arrange(Song(notes=notes, tempo_bpm=120.0, name="AB"),
                         style='faithful')
    assert stats['positions'] == 2 and stats['patterns'] == 2
    assert parse_module(pt3).order == [0, 1]


def test_echo_repeats_the_lead_delayed_and_quieter():
    pt3, stats = arrange(_chord_song(), style='faithful', echo=True)
    assert stats['echo'] is True
    assert stats['voices']['channel_c'] == 'echo'
    assert stats['voices']['echo'] > 0
    m = parse_module(pt3)
    lead = {r: ev for r, ev in enumerate(m.patterns[0][0])
            if ev is not None and ev.note is not None}
    echoes = {r: ev for r, ev in enumerate(m.patterns[0][2])
              if ev is not None and ev.note is not None}
    # every echo onset is a lead onset 2 rows (half a beat at rpb=4) earlier...
    assert echoes
    assert all(r - 2 in lead and ev.note == lead[r - 2].note
               for r, ev in echoes.items())
    # ...and quieter
    assert all(ev.vol < lead[r - 2].vol for r, ev in echoes.items())
    # the row invariant holds with the silent lead-in on channel C
    for (a, b, c) in _pattern_channel_addrs(pt3, stats['patterns']):
        for addr in (a, b, c):
            assert decode_row_count(pt3[addr:]) == ROWS_PER_PATTERN


def test_echo_carries_the_chiptune_octave_ornament():
    # short lead notes get the octave ornament in chiptune style; the echo is
    # built after that pass, so it must carry the ornament too
    from spectrumizer.pt3 import ORN_OCTAVE
    notes = []
    for beat in range(8):
        notes.append(Note(pitch=72, start=beat, dur=0.5))   # short -> octave orn
        notes.append(Note(pitch=48, start=beat, dur=1))     # bass
    pt3, stats = arrange(Song(notes=notes, tempo_bpm=120.0, name="ECHO"),
                         style='chiptune', echo=True)
    assert stats['voices']['channel_c'] == 'echo'
    assert ORN_OCTAVE in _channel_c_ornaments(pt3)


def test_channel_c_priority_drums_then_arps_then_echo():
    song = _triad_song()
    _, stats = arrange(song, style='faithful', arps=True, echo=True)
    assert stats['voices']['channel_c'] == 'arp'      # arps outrank echo
    song.drums = [Note(pitch=36, start=b, dur=0.25) for b in range(8)]
    _, stats = arrange(song, style='faithful', arps=True, echo=True)
    assert stats['voices']['channel_c'].startswith('drums')   # drums outrank both


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


def _shifted_chord_song(offset):
    song = _chord_song()
    for n in song.notes:
        n.pitch += offset
    return song


def test_auto_transpose_brings_extreme_registers_back():
    # the same piece written two octaves up / down must come back to the
    # comfortable register — and by whole octaves, so the key is untouched
    reference, _ = arrange(_chord_song())
    high, sh = arrange(_shifted_chord_song(24), auto_transpose=True)
    low, sl = arrange(_shifted_chord_song(-24), auto_transpose=True)
    assert sh['transpose'] == -24 and sl['transpose'] == 24
    assert high == reference and low == reference


def test_auto_transpose_is_a_noop_when_comfortable():
    plain, _ = arrange(_chord_song())
    auto, stats = arrange(_chord_song(), auto_transpose=True)
    assert stats['transpose'] == 0 and stats['auto_transpose'] is True
    assert auto == plain


def test_auto_transpose_keeps_the_manual_offset_on_top():
    _, stats = arrange(_shifted_chord_song(24), auto_transpose=True,
                       transpose=-12)
    assert stats['transpose'] == -36


def test_auto_transpose_shift_of_nothing_is_zero():
    from spectrumizer.arrange import auto_transpose_shift
    assert auto_transpose_shift([]) == 0


def test_vibrato_swaps_the_lead_sample():
    from spectrumizer.pt3 import S_LEAD, S_LEAD_VIB
    song = _chord_song()
    plain, _ = arrange(song)
    vib, sv = arrange(song, vibrato=True)
    assert sv['vibrato'] is True
    lead = [ev for ev in parse_module(vib).patterns[0][0]
            if ev is not None and ev.note is not None]
    assert lead and all(ev.sample == S_LEAD_VIB for ev in lead)
    lead_plain = [ev for ev in parse_module(plain).patterns[0][0]
                  if ev is not None and ev.note is not None]
    assert all(ev.sample == S_LEAD for ev in lead_plain)
    # an echo mirrors the lead's timbre, so it inherits the vibrato sample
    eco, _ = arrange(song, echo=True, vibrato=True)
    c_evs = [ev for ev in parse_module(eco).patterns[0][2]
             if ev is not None and ev.note is not None]
    assert c_evs and all(ev.sample == S_LEAD_VIB for ev in c_evs)


def test_stats_report_the_quantised_effective_tempo():
    # 110 bpm at 4 rows/beat wants 6.8 frames/row; the 50 Hz player only does
    # whole frames, so speed 7 really plays 3000/(7*4) = 107.1 bpm.
    song = _chord_song()
    song.tempo_bpm = 110.0
    _, stats = arrange(song)
    assert stats['speed'] == 7
    assert stats['tempo_bpm'] == 110.0
    assert stats['effective_bpm'] == 107.1
    # a tempo that divides 3000 exactly stays exact
    song.tempo_bpm = 125.0
    _, stats = arrange(song)
    assert stats['effective_bpm'] == 125.0 == stats['tempo_bpm']
