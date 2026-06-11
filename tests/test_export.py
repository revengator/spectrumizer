"""PT3 -> MIDI export: the reverse pipeline (module_to_song + write_midi)."""

from spectrumizer.ir import Song, Note
from spectrumizer.arrange import arrange
from spectrumizer.pt3.player import ParsedOrnament, parse_module, parse_sample
from spectrumizer.export import (module_to_song, write_midi, _drum_key,
                                 _chord_offsets)


def _three_voice_song():
    # half notes so the skyline is stable: top 72/74, middle 64, bottom 48.
    # 125 bpm divides the 50 Hz grid exactly (speed 6), so tempo round-trips.
    notes = []
    for beat in range(0, 16, 2):
        notes.append(Note(pitch=72 + beat % 4, start=beat, dur=2, velocity=127))
        notes.append(Note(pitch=64, start=beat, dur=2, velocity=127))
        notes.append(Note(pitch=48, start=beat, dur=2, velocity=127))
    return Song(notes=notes, tempo_bpm=125.0, name="ROUNDTRIP")


def test_export_roundtrips_the_arrangement():
    src = _three_voice_song()
    pt3, _ = arrange(src)                       # faithful: A=lead B=bass C=harm
    song = module_to_song(parse_module(pt3))
    assert song.tempo_bpm == 125.0
    assert song.name == "ROUNDTRIP"
    track_of = {72: 0, 74: 0, 48: 1, 64: 2}
    want = {(track_of[n.pitch], n.pitch, float(n.start), 2.0)
            for n in src.notes}
    got = {(n.track, n.pitch, n.start, n.dur) for n in song.notes}
    assert got == want
    # velocities come back from the per-channel AY volume ceilings (15/14/10)
    vels = {ci: {n.velocity for n in song.notes if n.track == ci}
            for ci in range(3)}
    assert vels == {0: {127}, 1: {119}, 2: {85}}


def test_pattern_boundary_reattacks_merge_back():
    # a 24-beat note spans the 64-row pattern boundary; the encoder re-attacks
    # it there (channel-length invariant) and the export merges it back
    src = Song(notes=[Note(pitch=69, start=0, dur=24, velocity=100),
                      Note(pitch=45, start=0, dur=24, velocity=100)],
               tempo_bpm=125.0)
    module = parse_module(arrange(src)[0])
    merged = [n for n in module_to_song(module).notes if n.track == 0]
    assert [(n.start, n.dur) for n in merged] == [(0.0, 24.0)]
    kept = [n for n in module_to_song(module, merge_boundaries=False).notes
            if n.track == 0]
    assert [(n.start, n.dur) for n in kept] == [(0.0, 16.0), (16.0, 8.0)]


def test_drum_classifier_by_noise_colour():
    from spectrumizer.pt3 import samples as smp
    key = lambda blob: _drum_key(parse_sample(blob, 0))
    assert key(smp.build_kick()) == 36          # dark noise period
    assert key(smp.build_snare()) == 38         # mid
    assert key(smp.build_hat()) == 42           # bright, short
    assert key(smp.build_hat_open()) == 46      # bright, rings on
    # pitched stays pitched: sustaining loops, or no noise at all (buzzer)
    assert key(smp.build_lead()) is None
    assert key(smp.build_bass()) is None        # noisy attack but held tail
    assert key(smp.build_buzzer()) is None


def test_gm_drums_roundtrip():
    melody = [Note(pitch=72, start=b, dur=1, velocity=127) for b in range(4)]
    bass = [Note(pitch=48, start=b, dur=1, velocity=127) for b in range(4)]
    drums = [Note(pitch=36, start=0, dur=.25, velocity=127),
             Note(pitch=42, start=1, dur=.25, velocity=127),
             Note(pitch=38, start=2, dur=.25, velocity=127),
             Note(pitch=46, start=3, dur=.25, velocity=127)]
    src = Song(notes=melody + bass, drums=drums, tempo_bpm=125.0)
    song = module_to_song(parse_module(arrange(src)[0]))
    assert {(n.pitch, n.start) for n in song.drums} == \
        {(36, 0.0), (42, 1.0), (38, 2.0), (46, 3.0)}


def test_arp_ornaments_export_as_chords():
    # an Am7 stack arranged with --arps: channel C plays the root + the min7
    # ornament — the export expands it back into the four real pitches
    chord = [Note(pitch=p, start=0, dur=4, velocity=100) for p in (45, 48, 52, 55)]
    melody = [Note(pitch=69, start=b, dur=2, velocity=100) for b in (0, 2)]
    src = Song(notes=chord + melody, tempo_bpm=125.0)
    song = module_to_song(parse_module(arrange(src, arps=True)[0]))
    assert {n.pitch for n in song.notes if n.track == 2 and n.start == 0} == \
        {45, 48, 52, 55}


def test_chord_offsets_filter():
    orn = lambda offs: ParsedOrnament(0, list(offs))
    assert _chord_offsets(orn([0, 4, 7])) == [0, 4, 7]
    assert _chord_offsets(orn([0, 0, 3, 3, 7, 7, 10, 10])) == [0, 3, 7, 10]
    assert _chord_offsets(orn([0, 2, 7])) == [0, 2, 7]   # sus2's 2-semitone step
    assert _chord_offsets(orn([0, 1])) == [0]            # trill
    assert _chord_offsets(orn([0, 12])) == [0]           # octave embellishment
    assert _chord_offsets(orn([0, -1, 1])) == [0]        # vibrato
    assert _chord_offsets(orn([0])) == [0]
    assert _chord_offsets(None) == [0]


def test_written_midi_reads_back(tmp_path):
    import mido
    src = _three_voice_song()
    song = module_to_song(parse_module(arrange(src)[0]))
    out = tmp_path / "roundtrip.mid"
    write_midi(song, str(out))
    mid = mido.MidiFile(str(out))
    assert mid.type == 1 and len(mid.tracks) == 4      # tempo meta + A + B + C
    tempo = next(m.tempo for t in mid.tracks for m in t if m.type == 'set_tempo')
    assert round(mido.tempo2bpm(tempo), 1) == 125.0
    ons = [m for t in mid.tracks for m in t if m.type == 'note_on']
    assert len(ons) == len(song.notes)
