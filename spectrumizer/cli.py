"""spectrumize CLI: MIDI -> PT3."""

from __future__ import annotations

import argparse
import os
import sys


LICENCE_REMINDER = (
    "reminder: the OUTPUT inherits the SOURCE's licence. Only bundle public-domain "
    "or your own music into a release. See spectrumizer/LICENSING.md."
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spectrumize",
        description="Generate ZX Spectrum AY (PT3) music from a MIDI source.")
    p.add_argument("input", help="input .mid / .midi file")
    p.add_argument("-o", "--output", help="output .pt3 (default: input with .pt3)")
    p.add_argument("--style", choices=["faithful", "chiptune"], default="faithful",
                   help="faithful 3-voice reduction, or chiptune embellishments "
                        "(octave leads + synth drums). Default: faithful.")
    p.add_argument("--rows-per-beat", type=int, default=4,
                   help="grid resolution (4 = sixteenth notes). Default: 4.")
    p.add_argument("--speed", type=int, default=None,
                   help="PT3 speed (frames/row). Default: derived from tempo.")
    p.add_argument("--transpose", type=int, default=0,
                   help="semitones to shift all pitches (tune AY octave by ear).")
    p.add_argument("--name", default=None, help="PT3 module title (<=32 chars).")
    p.add_argument("--author", default="SPECTRUMIZER",
                   help="PT3 module author (<=32 chars).")
    p.add_argument("--loop-pos", type=int, default=0,
                   help="position to loop back to after the song ends. Default 0.")
    p.add_argument("--no-dynamics", dest="dynamics", action="store_false",
                   help="flat per-channel volume instead of mapping MIDI velocity "
                        "to AY volume (dynamics are on by default).")
    p.add_argument("--play", action="store_true",
                   help="after writing the .pt3, render it to audio and play it "
                        "(software AY). See also the `spectrumize-play` command.")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="suppress the stats summary.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"spectrumize: input not found: {args.input}", file=sys.stderr)
        return 2

    out = args.output or (os.path.splitext(args.input)[0] + ".pt3")

    # Imported lazily so `--help` works without mido installed.
    from .inputs.midi import load_midi
    from .arrange import arrange

    song = load_midi(args.input)
    if not song.notes and not song.drums:
        print("spectrumize: no notes found in input.", file=sys.stderr)
        return 1

    pt3, stats = arrange(
        song, style=args.style, rows_per_beat=args.rows_per_beat,
        speed=args.speed, transpose=args.transpose,
        name=args.name, author=args.author, loop_pos=args.loop_pos,
        dynamics=args.dynamics)

    with open(out, "wb") as f:
        f.write(pt3)

    if not args.quiet:
        v = stats["voices"]
        print(f"spectrumize: {args.input} -> {out}")
        print(f"  style={stats['style']}  speed={stats['speed']}  "
              f"tempo~{stats['tempo_bpm']}bpm  patterns={stats['patterns']}  "
              f"bytes={stats['bytes']}")
        print(f"  A=lead({v['lead']})  B=bass({v['bass']})  "
              f"C={v['channel_c']}"
              + (f"({v['harmony']})" if v['channel_c'] == 'harmony' else "")
              + (f"  drums={v['drums']}" if v['drums'] else ""))
        print(f"  {LICENCE_REMINDER}")

    if args.play:
        from .pt3.player import parse_module
        from . import audio
        module = parse_module(pt3)
        wav = os.path.splitext(out)[0] + ".wav"
        pcm, channels = audio.render_pcm(module)
        audio.write_wav(wav, pcm, channels=channels)
        if not args.quiet:
            print(f"  playing {wav} ...")
        if not audio.play_wav(wav):
            print(f"spectrumize: no system audio player found; open {wav} manually.",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
