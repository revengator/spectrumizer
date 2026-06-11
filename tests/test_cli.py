"""CLI surfaces: --version on every entry point, foreign-module warnings."""

import pytest

from spectrumizer import __version__


def _foreign_pt3():
    # a channel with a token spectrumizer never emits (0x05) + tone table 2
    from spectrumizer.pt3 import build_pt3, DEFAULT_SAMPLES, DEFAULT_ORNAMENTS
    foreign = bytes([0xC5, 0xB1, 0x40, 0x05, 0x50, 0x00])  # vol, skip 64, ?, C-1
    return build_pt3([(foreign, foreign, foreign)], dict(DEFAULT_SAMPLES),
                     dict(DEFAULT_ORNAMENTS), name="FOREIGN", tone_table=2)


def test_version_flags(capsys):
    from spectrumizer.cli import main as gen_main
    from spectrumizer.play import main as play_main
    from spectrumizer.pack import main as pack_main
    from spectrumizer.export import main as export_main
    for entry, prog in ((gen_main, "spectrumizer"),
                        (play_main, "spectrumizer-play"),
                        (pack_main, "spectrumizer-pack"),
                        (export_main, "spectrumizer-export")):
        with pytest.raises(SystemExit) as e:
            entry(["--version"])
        assert e.value.code == 0
        assert capsys.readouterr().out.strip() == f"{prog} {__version__}"


def test_play_warns_on_foreign_module(tmp_path, capsys):
    from spectrumizer.play import main as play_main
    src = tmp_path / "foreign.pt3"
    src.write_bytes(_foreign_pt3())
    assert play_main([str(src), "--no-play", "-q", "--rate", "8000"]) == 0
    err = capsys.readouterr().err
    assert "outside the decoded subset" in err and "0x05" in err
    assert "tone table 2" in err


def test_export_cli_writes_midi_and_warns(tmp_path, capsys):
    import mido
    from spectrumizer.export import main as export_main
    src = tmp_path / "foreign.pt3"
    src.write_bytes(_foreign_pt3())
    out = tmp_path / "foreign.mid"
    assert export_main([str(src), "-o", str(out)]) == 0
    captured = capsys.readouterr()
    assert "outside the decoded subset" in captured.err
    assert "licence" in captured.out          # the output inherits the source's
    mid = mido.MidiFile(str(out))
    assert any(m.type == 'note_on' for t in mid.tracks for m in t)
