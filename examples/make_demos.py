"""Render one demo per use-case into docs/audio/ and build the demos page.

Each clip is examples/ode-to-joy.mid rendered through spectrumizer's own
software AY, so visitors can hear every mode on the GitHub Pages site
(docs/index.html) in the browser with nothing to install. MP3s are encoded with
`lameenc` — a pip wheel that bundles LAME, so there's no system ffmpeg needed:

    pip install -e ".[demos]"      # or: pip install lameenc
    python examples/make_demos.py
"""

from __future__ import annotations

import html
import os

from spectrumizer.inputs.midi import load_midi
from spectrumizer.arrange import arrange
from spectrumizer.pt3.player import parse_module
from spectrumizer import audio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "ode-to-joy.mid")
OUT = os.path.join(ROOT, "docs", "audio")
RATE = 22050     # smaller files; still well above the AY's useful bandwidth
BITRATE = 128    # kbps; plenty for the AY's simple spectrum

# slug, title, blurb, CLI command, arrange kwargs, render kwargs
DEMOS = [
    ("faithful", "Faithful (3-voice reduction)",
     "Straight reduction of the source to lead / bass / harmony.",
     "spectrumizer ode-to-joy.mid -o faithful.pt3",
     dict(style="faithful"), dict()),
    ("chiptune", "Chiptune",
     "Octave-doubled lead + synth drums — the default chiptune flavour.",
     "spectrumizer ode-to-joy.mid -o chiptune.pt3 --style chiptune",
     dict(style="chiptune"), dict()),
    ("buzzer", "Buzzer bass (pure envelope)",
     "Channel B is the AY hardware envelope itself, oscillating at the note "
     "pitch with the tone off — the characteristic deep AY buzzer. Pitch is "
     "inherently coarse, so it sits best on low bass lines.",
     "spectrumizer ode-to-joy.mid --style chiptune --bass envelope",
     dict(style="chiptune", bass="envelope"), dict()),
    ("buzzer-tone", "Buzzer bass (tone + envelope)",
     "Tone keeps the exact pitch while the hardware envelope adds the buzz — "
     "pitch-accurate at any register.",
     "spectrumizer ode-to-joy.mid --style chiptune --bass envelope-tone",
     dict(style="chiptune", bass="envelope-tone"), dict()),
    ("chiptune-flat", "No dynamics",
     "Flat per-channel volume; compare with the chiptune clip to hear the "
     "velocity-driven dynamics.",
     "spectrumizer ode-to-joy.mid --style chiptune --no-dynamics",
     dict(style="chiptune", dynamics=False), dict()),
    ("chiptune-equal", "Equal-tempered tuning",
     "Equal temperament instead of the exact PT3 tone table — slightly off "
     "from where the chip actually plays.",
     "spectrumizer-play chiptune.pt3 --tuning equal",
     dict(style="chiptune"), dict(tuning="equal")),
    ("chiptune-mono", "Mono",
     "Mono instead of the default ABC stereo (A-left / B-centre / C-right).",
     "spectrumizer-play chiptune.pt3 --stereo mono",
     dict(style="chiptune"), dict(stereo="mono")),
]

_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>spectrumizer — demos</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 46rem; margin: 2rem auto;
         padding: 0 1rem; }}
  h1 {{ margin-bottom: .2rem; }}
  .sub {{ opacity: .7; margin-top: 0; }}
  .demo {{ border-top: 1px solid #8884; padding: 1rem 0; }}
  .demo h2 {{ margin: 0 0 .25rem; font-size: 1.1rem; }}
  .demo p {{ margin: .25rem 0; }}
  audio {{ width: 100%; margin: .4rem 0; }}
  code {{ background: #8881; padding: .1em .35em; border-radius: .3em; }}
  footer {{ opacity: .7; font-size: .9rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h1>spectrumizer — demos</h1>
<p class="sub">MIDI &rarr; ZX Spectrum AY (PT3). Every clip is
<code>examples/ode-to-joy.mid</code> rendered through spectrumizer's software AY.</p>
{items}
<footer>Regenerate with <code>python examples/make_demos.py</code>.
See the <a href="https://github.com/revengator/spectrumizer">repository</a>.</footer>
</body>
</html>
"""

_ITEM = """\
<div class="demo">
  <h2>{title}</h2>
  <p>{blurb}</p>
  <audio controls preload="none" src="audio/{slug}.mp3"></audio>
  <p><code>{cmd}</code> &middot; <a href="audio/{slug}.pt3">download .pt3</a></p>
</div>
"""


def _encode_mp3(path: str, pcm, channels: int, sample_rate: int,
                bitrate: int = BITRATE) -> int:
    import lameenc
    enc = lameenc.Encoder()
    enc.set_bit_rate(bitrate)
    enc.set_in_sample_rate(sample_rate)
    enc.set_channels(channels)
    enc.set_quality(2)                       # 2 = high
    data = enc.encode(pcm.tobytes()) + enc.flush()
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def main() -> None:
    try:
        import lameenc  # noqa: F401
    except ImportError:
        raise SystemExit("make_demos needs lameenc: pip install -e '.[demos]' "
                         "(or pip install lameenc)")

    os.makedirs(OUT, exist_ok=True)
    song = load_midi(SRC)
    items = []
    for slug, title, blurb, cmd, akw, rkw in DEMOS:
        pt3, _ = arrange(song, **akw)
        with open(os.path.join(OUT, slug + ".pt3"), "wb") as f:
            f.write(pt3)
        module = parse_module(pt3)
        pcm, ch = audio.render_pcm(module, sample_rate=RATE, **rkw)
        kb = _encode_mp3(os.path.join(OUT, slug + ".mp3"), pcm, ch, RATE) / 1024
        items.append(_ITEM.format(title=html.escape(title), blurb=html.escape(blurb),
                                  slug=slug, cmd=html.escape(cmd)))
        print(f"  {slug}.mp3  ({ch}ch, {kb:.0f} KB)")

    page = _PAGE.format(items="".join(items))
    with open(os.path.join(ROOT, "docs", "index.html"), "w") as f:
        f.write(page)
    print(f"  docs/index.html ({len(DEMOS)} demos)")


if __name__ == "__main__":
    main()
