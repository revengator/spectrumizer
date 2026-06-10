"""MIDI -> IR adapter."""

import mido

from spectrumizer.inputs.midi import load_midi


def _write_midi(path):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120), time=0))
    # two melody notes on ch0 (1 beat each)
    tr.append(mido.Message('note_on', note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message('note_off', note=60, velocity=0, channel=0, time=480))
    tr.append(mido.Message('note_on', note=64, velocity=100, channel=0, time=0))
    tr.append(mido.Message('note_off', note=64, velocity=0, channel=0, time=480))
    # a kick on the GM drum channel (ch9)
    tr.append(mido.Message('note_on', note=36, velocity=100, channel=9, time=0))
    tr.append(mido.Message('note_off', note=36, velocity=0, channel=9, time=120))
    mid.save(path)


def test_load_midi_notes_drums_tempo(tmp_path):
    p = tmp_path / "t.mid"
    _write_midi(str(p))
    song = load_midi(str(p))

    assert len(song.notes) == 2
    assert {n.pitch for n in song.notes} == {60, 64}
    assert len(song.drums) == 1 and song.drums[0].pitch == 36
    assert song.has_drums
    assert abs(song.tempo_bpm - 120.0) < 0.5
    # times are in beats; the first melody note starts at beat 0, lasts 1 beat
    first = sorted(song.notes, key=lambda n: n.start)[0]
    assert abs(first.start) < 1e-6 and abs(first.dur - 1.0) < 1e-3


def test_tempo_changes_fold_into_the_dominant_tempo(tmp_path):
    # 1 beat @120 then 4 beats @60: 60 bpm wins by wall-clock, so the grid is
    # 60 bpm and the @120 note shrinks to half a reference beat (same seconds).
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120), time=0))
    tr.append(mido.Message('note_on', note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message('note_off', note=60, velocity=0, channel=0, time=480))
    tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(60), time=0))
    tr.append(mido.Message('note_on', note=64, velocity=100, channel=0, time=0))
    tr.append(mido.Message('note_off', note=64, velocity=0, channel=0,
                           time=4 * 480))
    p = tmp_path / "t.mid"
    mid.save(str(p))

    song = load_midi(str(p))
    assert abs(song.tempo_bpm - 60.0) < 0.5
    a, b = sorted(song.notes, key=lambda n: n.start)
    assert abs(a.start - 0.0) < 1e-6 and abs(a.dur - 0.5) < 1e-3
    assert abs(b.start - 0.5) < 1e-6 and abs(b.dur - 4.0) < 1e-3


def test_reemitted_same_tempo_keeps_the_plain_grid(tmp_path, capsys):
    # The same tempo re-emitted mid-file (common in DAW exports) is not a
    # tempo change: the plain ticks/beat grid applies and nothing is printed.
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(100), time=0))
    tr.append(mido.Message('note_on', note=60, velocity=100, channel=0, time=0))
    tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(100), time=240))
    tr.append(mido.Message('note_off', note=60, velocity=0, channel=0, time=240))
    p = tmp_path / "s.mid"
    mid.save(str(p))

    song = load_midi(str(p))
    assert abs(song.tempo_bpm - 100.0) < 0.5
    assert abs(song.notes[0].dur - 1.0) < 1e-3
    assert "tempo map" not in capsys.readouterr().err


def test_restruck_pitch_closes_the_open_note(tmp_path):
    # the same pitch re-struck while still sounding (legato retrigger) must
    # close the first note at the re-strike, not silently drop it
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.Message('note_on', note=60, velocity=100, channel=0, time=0))
    tr.append(mido.Message('note_on', note=60, velocity=80, channel=0, time=480))
    tr.append(mido.Message('note_off', note=60, velocity=0, channel=0, time=480))
    p = tmp_path / "r.mid"
    mid.save(str(p))

    song = load_midi(str(p))
    notes = sorted(song.notes, key=lambda n: n.start)
    assert len(notes) == 2
    assert abs(notes[0].start - 0.0) < 1e-6 and abs(notes[0].dur - 1.0) < 1e-3
    assert abs(notes[1].start - 1.0) < 1e-6 and abs(notes[1].dur - 1.0) < 1e-3
    assert notes[0].velocity == 100 and notes[1].velocity == 80
