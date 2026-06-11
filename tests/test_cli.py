"""CLI surfaces: --version on every entry point, audition warnings."""

import pytest

from spectrumizer import __version__


def test_version_flags(capsys):
    from spectrumizer.cli import main as gen_main
    from spectrumizer.play import main as play_main
    from spectrumizer.pack import main as pack_main
    for entry, prog in ((gen_main, "spectrumizer"),
                        (play_main, "spectrumizer-play"),
                        (pack_main, "spectrumizer-pack")):
        with pytest.raises(SystemExit) as e:
            entry(["--version"])
        assert e.value.code == 0
        assert capsys.readouterr().out.strip() == f"{prog} {__version__}"


def test_play_warns_on_foreign_module(tmp_path, capsys):
    from spectrumizer.pt3 import build_pt3, DEFAULT_SAMPLES, DEFAULT_ORNAMENTS
    from spectrumizer.play import main as play_main
    foreign = bytes([0xC5, 0xB1, 0x40, 0x05, 0x50, 0x00])  # vol, skip 64, ?, C-1
    pt3 = build_pt3([(foreign, foreign, foreign)], dict(DEFAULT_SAMPLES),
                    dict(DEFAULT_ORNAMENTS), name="FOREIGN", tone_table=2)
    src = tmp_path / "foreign.pt3"
    src.write_bytes(pt3)
    assert play_main([str(src), "--no-play", "-q", "--rate", "8000"]) == 0
    err = capsys.readouterr().err
    assert "outside the audition subset" in err and "0x05" in err
    assert "tone table 2" in err
