"""Chiptune embellishers (composable passes selected by style / flags).

Passes:
  * octave_short_lead — octave-double SHORT lead notes (the classic AY brightener;
    held notes stay single-voice so they don't warble).
  * synth_drums       — a backbeat (kick on beats 1&3, snare on 2&4, closed
    hats on the off-eighths, an open hat closing each bar) when the source has
    no drum track, so chiptune output still has percussive drive.
  * chord_arps        — fake polyphony on one channel: play each chord's root and
    cycle the matching interval ornament (triads, sevenths, sus2/sus4) at frame
    rate, so a single AY channel implies the whole chord (the classic AY/Follin
    trick).
  * echo_lead         — a delayed, quieter copy of the lead on a free channel
    (the other classic AY trick).
  * multiplex_drums_harmony — drums + harmony time-shared on one channel: drum
    hits (1 row each) win their rows, the harmony fills the gaps and re-attacks
    right after a hit that lands inside one of its notes (the classic tracker
    interleave).
"""

from __future__ import annotations

from .model import Placed
from .chords import identify_chord, group_by_onset
from .quantize import note_rows
from ..ir import Note
from ..pt3 import (midi_to_pt3_byte, ORN_OCTAVE, ORN_EMPTY, ORN_MAJOR,
                   ORN_MINOR, ORN_DOM7, ORN_MAJ7, ORN_MIN7, ORN_SUS2, ORN_SUS4)

_ARP_ORN = {'maj': ORN_MAJOR, 'min': ORN_MINOR, 'dom7': ORN_DOM7,
            'maj7': ORN_MAJ7, 'min7': ORN_MIN7,
            'sus2': ORN_SUS2, 'sus4': ORN_SUS4}


def octave_short_lead(lead: list[Placed], short_thresh_rows: int) -> None:
    """In place: octave ornament on notes shorter than the threshold."""
    for p in lead:
        p.opts['ornament'] = ORN_OCTAVE if (p.end - p.start) < short_thresh_rows else ORN_EMPTY


def synth_drums(total_rows: int, rows_per_beat: int, drum_byte: int,
                snare_sample: int, kick_sample: int,
                hat_sample: int | None = None,
                hat_open_sample: int | None = None) -> list[Placed]:
    """A 4/4 backbeat occupying one channel (drums = noise, tone off): kick on
    beats 1 & 3, snare on 2 & 4 and — given the hat samples and a grid fine
    enough for them — a quieter closed hat on every off-eighth, the bar's last
    one opened so it sizzles into the next bar. Every event states its volume:
    the encoder only re-emits it on change, and the hats run quieter."""
    placed: list[Placed] = []
    half = rows_per_beat // 2
    for b in range(total_rows // rows_per_beat):
        row = b * rows_per_beat
        sample = kick_sample if b % 4 in (0, 2) else snare_sample
        placed.append(Placed(row, row + 1, drum_byte,
                             {'sample': sample, 'vol': 13}))
        if hat_sample is None or not half or row + half >= total_rows:
            continue
        bar_end = b % 4 == 3 and hat_open_sample is not None
        placed.append(Placed(row + half, row + half + 1, drum_byte,
                             {'sample': hat_open_sample if bar_end else hat_sample,
                              'vol': 10 if bar_end else 9}))
    return placed


def chord_arps(notes: list[Note], rows_per_beat: int, total_rows: int,
               transpose: int = 0, vol_fn=None) -> list[Placed]:
    """Build a single-channel arpeggio line from the source chords.

    One Placed per onset that carries notes: a recognised chord (major/minor
    triad, dominant/major/minor seventh, sus2/sus4) becomes its root note +
    the matching arp ornament (so the one channel cycles the chord tones and
    implies the harmony); anything else falls back to the group's lowest note
    played plain, so the channel is never emptier than a held bass line.
    `vol_fn` (optional) maps the group's peak velocity to an AY volume for
    dynamics.
    """
    placed: list[Placed] = []
    # group by the row each onset quantises to, so humanised (slightly
    # staggered) chords are still seen as one chord
    for group in group_by_onset(notes, key=lambda s: round(s * rows_per_beat)):
        s, e = note_rows(min(n.start for n in group), max(n.end for n in group),
                         rows_per_beat, total_rows)
        if s >= total_rows:
            continue
        pitches = [n.pitch for n in group]
        chord = identify_chord(pitches)
        if chord is not None:
            root_pc, quality = chord
            root_pitch = min(p for p in pitches if p % 12 == root_pc)
            note_byte = midi_to_pt3_byte(root_pitch, transpose)
            ornament = _ARP_ORN[quality]
        else:
            note_byte = midi_to_pt3_byte(min(pitches), transpose)
            ornament = ORN_EMPTY
        opts: dict = {'ornament': ornament}
        if vol_fn is not None:
            opts['vol'] = vol_fn(max(n.velocity for n in group))
        placed.append(Placed(s, e, note_byte, opts))
    return placed


def multiplex_drums_harmony(drums: list[Placed],
                            harmony: list[Placed]) -> list[Placed]:
    """Time-share one channel between drums and harmony.

    Drums keep their (1-row) onset rows; each harmony note is split into the
    segments between the drum hits that fall inside it, re-attacking after
    every hit so the chord keeps sounding. Both voices must carry their own
    'sample' and 'vol' opts — the segments inherit them, and the encoder
    switches timbre/volume per event.
    """
    drum_rows = {p.start for p in drums}
    out = list(drums)
    for h in harmony:
        s = h.start
        while s < h.end:
            if s in drum_rows:              # a drum owns this row: resume after
                s += 1
                continue
            e = h.end
            for r in range(s + 1, h.end):   # segment ends at the next hit inside
                if r in drum_rows:
                    e = r
                    break
            out.append(Placed(s, e, h.note, dict(h.opts)))
            s = e
    return out


def echo_lead(lead: list[Placed], delay_rows: int, total_rows: int,
              level: int = 8) -> list[Placed]:
    """A delayed, quieter copy of the lead — the classic AY echo on a free
    channel. Each lead note repeats `delay_rows` later with its volume scaled
    by `level`/15 (a note with no explicit volume counts as 15). Everything
    else the note carries (ornaments — e.g. the chiptune octave) echoes with
    it, so run this AFTER the lead embellishments."""
    out: list[Placed] = []
    for p in lead:
        s = p.start + delay_rows
        if s >= total_rows:
            continue
        opts = dict(p.opts)
        opts['vol'] = max(1, round(opts.get('vol', 15) * level / 15))
        out.append(Placed(s, min(p.end + delay_rows, total_rows), p.note, opts))
    return out
