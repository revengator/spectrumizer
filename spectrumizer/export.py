"""spectrumizer-export CLI: PT3 -> MIDI (the reverse pipeline).

Decodes a `.pt3` back into notes (via `pt3.player`, the same decoder the
audition uses) and writes a standard MIDI file: channels A/B/C become three
tracks, percussive hits land on the GM drum channel, and chord-arp ornaments
are expanded back into the chords they fake. What comes back is the 3-channel
AY *arrangement* — embellishments (echo, octave leads) export as the notes
they actually play, and timbre (samples, buzzer, noise) has no MIDI analogue.
"""

from __future__ import annotations

import argparse
import os
import sys

from .ir import Song, Note
from .pt3.player import Module, ParsedOrnament, ParsedSample

PPQ = 480                       # MIDI ticks per quarter note


def _drum_key(sample: ParsedSample | None) -> int | None:
    """GM drum key for a percussive sample, or None for a pitched one.

    A drum here is a one-shot noise burst: some tick mixes the noise in AND
    the loop tick is silent. Pitched instruments sustain (the bass has a
    noisy attack but loops on a held tail; the buzzer never mixes noise).
    The key follows the noise character: dark period = kick, mid = snare,
    bright = hat — open if the burst rings on.
    """
    if sample is None:
        return None
    noisy = [t for t in sample.ticks if t[1]]            # noise_on ticks
    if not noisy or sample.ticks[sample.loop][2]:        # sustains: pitched
        return None
    period = noisy[0][4]                                 # first tick's AddToNs
    if period >= 12:
        return 36                                        # kick
    if period >= 3:
        return 38                                        # snare
    return 46 if len(sample.ticks) > 6 else 42           # open / closed hat


def _chord_offsets(orn: ParsedOrnament | None) -> list[int]:
    """Semitone offsets to expand an arp ornament back into its chord.

    A static cycle of 2-4 distinct upward intervals reads as a chord (the
    arranger's --arps fake; sus2's narrowest step is 2 semitones). Trills,
    vibratos, slides and the bare octave embellishment stay a single note —
    returns [0] for those.
    """
    if orn is None:
        return [0]
    unique = sorted(set(orn.offsets))
    if unique[0] != 0 or not 2 <= len(unique) <= 4 or unique[-1] > 24:
        return [0]
    gaps = [b - a for a, b in zip(unique, unique[1:])]
    if min(gaps) < 2 or (len(unique) == 2 and (gaps[0] < 3 or unique == [0, 12])):
        return [0]
    return unique


def module_to_song(module: Module, *, rows_per_beat: int = 4,
                   merge_boundaries: bool = True) -> Song:
    """Decode a parsed module into an IR `Song` — the inverse of `arrange`.

    Rows map to beats via `rows_per_beat` (PT3 does not store it; 4 matches
    the arranger's default sixteenth grid — it only moves the barlines, not
    the music). The tempo is the module's effective tempo (speed is whole
    frames per row). Notes the encoder re-attacked at pattern boundaries to
    keep them ringing are merged back into one note unless
    `merge_boundaries=False`.
    """
    rpb = rows_per_beat
    song = Song(name=module.name, tempo_bpm=3000.0 / (module.speed * rpb))

    # absolute-row timeline of the position list + the boundary rows where
    # held notes re-attack (see pt3.encode's channel-length invariant)
    starts: list[int] = []
    row0 = 0
    empty = ([], [], [])
    for pidx in module.order:
        starts.append(row0)
        pat = module.patterns[pidx] if pidx < len(module.patterns) else empty
        row0 += max((len(ch) for ch in pat), default=0)
    total_rows, boundaries = row0, set(starts[1:])

    for ci in range(3):
        open_notes: list[Note] = []          # the sounding note(s) (arps: chord)
        open_sig = None                      # (note, sample, ornament, vol)
        for pi, pidx in enumerate(module.order):
            pat = module.patterns[pidx] if pidx < len(module.patterns) else empty
            for r, ev in enumerate(pat[ci]):
                if ev is None:
                    continue
                row = starts[pi] + r
                sig = (ev.note, ev.sample, ev.ornament, ev.vol)
                if (merge_boundaries and row in boundaries and open_notes
                        and ev.note is not None and sig == open_sig):
                    continue                 # boundary re-attack: keep ringing
                for n in open_notes:         # close whatever was sounding
                    n.dur = row / rpb - n.start
                open_notes, open_sig = [], None
                if ev.note is None:          # OFF: silence until the next note
                    continue
                vel = max(1, round(ev.vol * 127 / 15))
                key = _drum_key(module.samples.get(ev.sample))
                if key is not None:          # drums ignore duration: one row
                    song.drums.append(Note(key, row / rpb, 1 / rpb, vel, ci))
                    continue
                pitch = ev.note - 0x50 + 24  # inverse of midi_to_pt3_byte
                for off in _chord_offsets(module.ornaments.get(ev.ornament)):
                    if 0 <= pitch + off <= 127:
                        note = Note(pitch + off, row / rpb, 1 / rpb, vel, ci)
                        open_notes.append(note)
                        song.notes.append(note)
                open_sig = sig
        for n in open_notes:                 # still ringing at the end
            n.dur = total_rows / rpb - n.start
    song.notes.sort(key=lambda n: (n.start, n.track, n.pitch))
    song.drums.sort(key=lambda n: (n.start, n.pitch))
    return song


_TRACK_NAMES = {0: "A (lead)", 1: "B (bass)", 2: "C"}


def write_midi(song: Song, path: str) -> None:
    """Write `song` as a type-1 MIDI file: a tempo track, one track per AY
    channel that has notes (MIDI channels 1-3), drums on GM channel 10."""
    import mido

    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage('track_name',
                                 name=song.name or 'spectrumizer', time=0))
    meta.append(mido.MetaMessage('set_tempo',
                                 tempo=mido.bpm2tempo(song.tempo_bpm), time=0))
    mid.tracks.append(meta)

    def add_track(name: str, events: list) -> None:
        # events: (tick, prio, message); note_offs (prio 0) precede note_ons
        # at the same tick so abutting same-pitch notes never overlap
        track = mido.MidiTrack()
        track.append(mido.MetaMessage('track_name', name=name, time=0))
        t = 0
        for tick, _prio, msg in sorted(events, key=lambda e: (e[0], e[1])):
            msg.time = tick - t
            t = tick
            track.append(msg)
        mid.tracks.append(track)

    for ci in range(3):
        events = []
        for n in (n for n in song.notes if n.track == ci):
            on, off = round(n.start * PPQ), round(n.end * PPQ)
            events.append((on, 1, mido.Message(
                'note_on', note=n.pitch, velocity=n.velocity, channel=ci)))
            events.append((max(on + 1, off), 0, mido.Message(
                'note_off', note=n.pitch, velocity=0, channel=ci)))
        if events:
            add_track(_TRACK_NAMES[ci], events)
    if song.drums:
        events = []
        for n in song.drums:
            on = round(n.start * PPQ)
            events.append((on, 1, mido.Message(
                'note_on', note=n.pitch, velocity=n.velocity, channel=9)))
            events.append((on + max(1, round(n.dur * PPQ)), 0, mido.Message(
                'note_off', note=n.pitch, velocity=0, channel=9)))
        add_track("drums", events)
    mid.save(path)


def build_parser() -> argparse.ArgumentParser:
    from . import __version__
    p = argparse.ArgumentParser(
        prog="spectrumizer-export",
        description="Export a PT3 module back to MIDI (notes, not timbre).")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("input", help="input .pt3 module")
    p.add_argument("-o", "--output", help="output .mid (default: input with .mid)")
    p.add_argument("--rows-per-beat", type=int, default=4,
                   help="how many PT3 rows make one beat (not stored in the "
                        "module; affects tempo/barlines only). Default: 4.")
    p.add_argument("--no-merge", action="store_true",
                   help="keep the re-attacks of notes held across pattern "
                        "boundaries instead of merging them into one note.")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="suppress the stats summary.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"spectrumizer-export: input not found: {args.input}",
              file=sys.stderr)
        return 2

    from .pt3.player import parse_module, foreign_warnings

    with open(args.input, "rb") as f:
        data = f.read()
    try:
        module = parse_module(data)
    except ValueError as e:
        print(f"spectrumizer-export: {e}", file=sys.stderr)
        return 1
    for w in foreign_warnings(module):
        print(f"spectrumizer-export: warning: {w}", file=sys.stderr)

    song = module_to_song(module, rows_per_beat=args.rows_per_beat,
                          merge_boundaries=not args.no_merge)
    if not song.notes and not song.drums:
        print("spectrumizer-export: no notes found in module.", file=sys.stderr)
        return 1

    out = args.output or (os.path.splitext(args.input)[0] + ".mid")
    write_midi(song, out)

    if not args.quiet:
        from .cli import LICENCE_REMINDER
        per = {ci: sum(1 for n in song.notes if n.track == ci) for ci in range(3)}
        print(f"spectrumizer-export: {args.input} -> {out}")
        print(f"  tempo~{round(song.tempo_bpm, 1)}bpm  "
              f"A={per[0]}  B={per[1]}  C={per[2]}"
              + (f"  drums={len(song.drums)}" if song.drums else ""))
        print(f"  {LICENCE_REMINDER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
