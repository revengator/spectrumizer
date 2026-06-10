"""Chiptune embellishers (composable passes selected by style / flags).

Passes:
  * octave_short_lead — octave-double SHORT lead notes (the classic AY brightener;
    held notes stay single-voice so they don't warble).
  * synth_drums       — a backbeat (kick on beats 1&3, snare on 2&4) when the
    source has no drum track, so chiptune output still has percussive drive.
  * chord_arps        — fake polyphony on one channel: play each chord's root and
    cycle a major/minor ornament (root, +third, +fifth) at 50 Hz, so a single AY
    channel implies the whole triad (the classic AY/Follin trick).
  * echo_lead         — a delayed, quieter copy of the lead on a free channel
    (the other classic AY trick).
  * multiplex_drums_harmony — drums + harmony time-shared on one channel: drum
    hits (1 row each) win their rows, the harmony fills the gaps and re-attacks
    right after a hit that lands inside one of its notes (the classic tracker
    interleave).
"""

from __future__ import annotations

from .model import Placed
from .chords import identify_triad, group_by_onset
from .quantize import note_rows
from ..ir import Note
from ..pt3 import midi_to_pt3_byte, ORN_OCTAVE, ORN_EMPTY, ORN_MAJOR, ORN_MINOR

_ARP_ORN = {'maj': ORN_MAJOR, 'min': ORN_MINOR}


def octave_short_lead(lead: list[Placed], short_thresh_rows: int) -> None:
    """In place: octave ornament on notes shorter than the threshold."""
    for p in lead:
        p.opts['ornament'] = ORN_OCTAVE if (p.end - p.start) < short_thresh_rows else ORN_EMPTY


def synth_drums(total_rows: int, rows_per_beat: int, drum_byte: int,
                snare_sample: int, kick_sample: int) -> list[Placed]:
    """A simple 4/4 backbeat occupying one channel (drums = noise, tone off)."""
    placed: list[Placed] = []
    n_beats = total_rows // rows_per_beat
    for b in range(n_beats):
        row = b * rows_per_beat
        if row >= total_rows:
            break
        if b % 4 in (0, 2):
            placed.append(Placed(row, row + 1, drum_byte, {'sample': kick_sample}))
        else:
            placed.append(Placed(row, row + 1, drum_byte, {'sample': snare_sample}))
    return placed


def chord_arps(notes: list[Note], rows_per_beat: int, total_rows: int,
               transpose: int = 0, vol_fn=None) -> list[Placed]:
    """Build a single-channel arpeggio line from the source chords.

    One Placed per onset that carries notes: a recognised major/minor triad
    becomes its root note + the matching arp ornament (so the one channel cycles
    root/third/fifth and implies the chord); anything else falls back to the
    group's lowest note played plain, so the channel is never emptier than a
    held bass line. `vol_fn` (optional) maps the group's peak velocity to an AY
    volume for dynamics.
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
        triad = identify_triad(pitches)
        if triad is not None:
            root_pc, quality = triad
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
