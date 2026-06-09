"""spectrumizer-play CLI: render / listen to a PT3 module on this machine.

Parses a spectrumizer-generated `.pt3`, synthesises it through a small software
AY (see `spectrumizer.audio`), writes a `.wav`, and plays it with the system
audio player (afplay / ffplay / aplay / paplay / sox).
"""

from __future__ import annotations

import argparse
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spectrumizer-play",
        description="Render and listen to a spectrumizer PT3 module (AY -> WAV).")
    p.add_argument("input", help="input .pt3 module")
    p.add_argument("-o", "--output",
                   help="output .wav (default: input with .wav)")
    p.add_argument("--seconds", type=float, default=None,
                   help="cap length and loop the song's tail to fill it.")
    p.add_argument("--loops", type=int, default=1,
                   help="play the loop section this many times total. Default 1.")
    p.add_argument("--rate", type=int, default=44100,
                   help="output sample rate (Hz). Default 44100.")
    p.add_argument("--noise-period", type=int, default=None,
                   help="override the AY noise period (1..31, lower = brighter). "
                        "Default: track the module's real per-frame value.")
    p.add_argument("--tuning", choices=["pt3", "equal"], default="pt3",
                   help="'pt3' = exact PT3 tone table (real Spectrum pitch); "
                        "'equal' = equal-tempered approximation. Default pt3.")
    p.add_argument("--stereo", choices=["abc", "acb", "mono"], default="abc",
                   help="panning: abc (A-left/B-centre/C-right, classic ZX), "
                        "acb, or mono. Default abc.")
    p.add_argument("--separation", type=float, default=0.7,
                   help="stereo width 0..1 (0 = narrow, 1 = hard pan). Default 0.7.")
    p.add_argument("--no-play", action="store_true",
                   help="only write the .wav, don't play it.")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="suppress the summary line.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"spectrumizer-play: input not found: {args.input}", file=sys.stderr)
        return 2

    from .pt3.player import parse_module
    from . import audio

    with open(args.input, "rb") as f:
        data = f.read()
    try:
        module = parse_module(data)
    except ValueError as e:
        print(f"spectrumizer-play: {e}", file=sys.stderr)
        return 1

    out = args.output or (os.path.splitext(args.input)[0] + ".wav")
    pcm, channels = audio.render_pcm(
        module, sample_rate=args.rate, loops=args.loops, max_seconds=args.seconds,
        noise_period=args.noise_period, tuning=args.tuning,
        stereo=args.stereo, separation=args.separation)
    audio.write_wav(out, pcm, sample_rate=args.rate, channels=channels)

    if not args.quiet:
        secs = len(pcm) / channels / args.rate
        title = module.name or "(untitled)"
        print(f"spectrumizer-play: {args.input} -> {out}")
        print(f"  {title!r}  speed={module.speed}  patterns={len(module.patterns)}"
              f"  {secs:.1f}s @ {args.rate} Hz  {args.stereo}")

    if not args.no_play:
        if not audio.play_wav(out):
            print("spectrumizer-play: no system audio player found; "
                  f"open {out} manually.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
