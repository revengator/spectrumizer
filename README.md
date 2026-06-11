# spectrumizer

[![PyPI](https://img.shields.io/pypi/v/spectrumizer.svg)](https://pypi.org/project/spectrumizer/)
[![CI](https://github.com/revengator/spectrumizer/actions/workflows/ci.yml/badge.svg)](https://github.com/revengator/spectrumizer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Live demos](https://img.shields.io/badge/%E2%96%B6-live%20demos-brightgreen.svg)](https://revengator.github.io/spectrumizer/)

Generate **ZX Spectrum AY music (`.pt3`)** from MIDI — and get the notes back
**out of a `.pt3` into MIDI** too. The output is a standard Vortex Tracker /
Sergey Bulba PT3 module, so anything it produces drops straight into a Spectrum
game that ships a PT3 replayer.

Instead of typing every arrangement note-by-note in Python, you feed a source
file and spectrumizer arranges it down to the AY's 3 channels (+ noise).

**▶ Hear it in your browser:** [demo page](https://revengator.github.io/spectrumizer/)
· or the [Demos](#demos) section below.

> ⚠️ **Licence:** spectrumizer does **not** launder licences. The licence of the
> SOURCE governs the OUTPUT — a `.pt3` from a copyrighted MIDI is still
> copyrighted. Only bundle **public-domain or your own** music into a release.
> Read [`LICENSING.md`](LICENSING.md).

## Install

```bash
pip install spectrumizer    # from PyPI — installs spectrumizer / spectrumizer-play / spectrumizer-pack / spectrumizer-export
```

The `spectrumizer` and `spectrumizer-play` commands are pure-Python.
`spectrumizer-pack` (package a `.pt3` for an emulator) additionally needs
[**sjasmplus**](https://github.com/z00m128/sjasmplus) on PATH to assemble the player.

Or from a clone (for development):

```bash
pip install -e .                                                    # editable install
# ...or without installing the package:
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

All deps are pure-Python (`mido`), so the same wheels work on Intel & Apple
Silicon — no native build step.

## Use

```bash
# faithful 3-voice reduction
spectrumizer song.mid -o song.pt3                 # or: python -m spectrumizer song.mid -o song.pt3

# chiptune flavour: octave-doubled leads + a kick/snare/hi-hat groove when the
# source has no drum track
spectrumizer song.mid -o song.pt3 --style chiptune

# tune the AY octave by ear, change grid/tempo
spectrumizer song.mid --transpose -12 --rows-per-beat 4 --speed 6 \
    --name "MY THEME" --author "ME"

# ...or let it fit the register itself: whole-octave shift (key preserved) into
# the AY sweet spot; any --transpose is applied on top
spectrumizer song.mid --auto-transpose

# dynamics: MIDI velocity drives per-note volume (on by default)
spectrumizer song.mid -o song.pt3 --no-dynamics      # ...or flat per-channel volume

# buzzer bass: drive the bass through the AY hardware envelope
spectrumizer song.mid --bass envelope        # pure buzzer — envelope is the oscillator (deep, coarse pitch)
spectrumizer song.mid --bass envelope-tone   # tone keeps the pitch, envelope adds the buzz (any register)

# chord arpeggios: channel C plays each chord's root and cycles the matching
# interval ornament — one channel implies the whole chord (the classic AY trick).
# Recognises major/minor triads, dominant/major/minor sevenths and sus2/sus4.
spectrumizer song.mid --arps
spectrumizer song.mid --arps --arp-speed 2   # hold each tone 2 frames: audible ripple

# echo: channel C repeats the lead half a beat later, quieter (the other classic)
spectrumizer song.mid --echo

# delayed vibrato on the lead (sub-semitone, encoded inside the PT3 sample)
spectrumizer song.mid --vibrato

# generate and immediately hear it (renders through a software AY, then plays)
spectrumizer song.mid -o song.pt3 --play
```

Run `spectrumizer --help` for all flags.

## How it works

```
MIDI ─(inputs/midi.py, mido)→ IR ─(arrange/)→ 3 AY channels ─(pt3/)→ .pt3
```

- **`spectrumizer/inputs/`** — MIDI → IR (via `mido`). Tempo changes are folded
  into one fixed grid (PT3 has a single global speed): the tempo heard longest
  becomes the reference and other sections are time-scaled onto it, so
  wall-clock timing is preserved.
- **`spectrumizer/pt3/`** — the proven PT3 emitter (note encoding, channel packer,
  samples, ornaments, file writer). The byte format is verified against the real
  player; don't change it blindly.
- **`spectrumizer/arrange/`** — the hard part:
  - `quantize` — map time to PT3's row grid (derive `speed` from tempo).
  - `reduce` — peel the source polyphony into ≤3 monophonic lines (lead / bass /
    harmony) via a greedy high/low "skyline".
  - `embellish` — extra voices: octave leads + synth drums (a kick/snare
    backbeat with closed hats on the off-eighths and an open hat closing each
    bar; chiptune style),
    **chord arpeggios** (`--arps`) — each source chord becomes its root note plus
    the matching interval ornament cycling at frame rate, so one AY channel
    implies the full chord (`arrange/chords.py` recognises major/minor triads,
    dominant/major/minor sevenths and sus2/sus4; `--arp-speed N` holds each
    tone N frames, turning the 50 Hz blur into an audible ripple) — and
    **echo** (`--echo`) — the lead repeated half a beat later, quieter, on
    channel C.
  - dynamics — MIDI velocity → per-note AY volume, normalised so the piece's
    loudest note hits each channel's ceiling (on by default; `--no-dynamics`).
  - auto-transpose (`--auto-transpose`) — shift the piece by whole octaves
    (key preserved) so the duration-weighted bulk of its notes sits in the
    AY's comfortable register (up to PT3 octave 6 — clear of the coarse-pitch
    top octaves — and off the format floor), instead of tuning `--transpose`
    by ear. A well-registered piece shifts 0.
  - vibrato (`--vibrato`) — the lead's sustain wobbles the tone period (±3
    units at 6.25 Hz, delayed past the attack). PT3 samples carry a signed
    per-tick tone offset, so the vibrato lives inside the instrument and
    costs nothing in the patterns; an `--echo` inherits it.
  - buzzer bass — `--bass envelope` routes channel B through the AY **hardware
    envelope** at each note's pitch (the deep AY buzzer; pitch is coarse, best
    low). `--bass envelope-tone` keeps the tone for exact pitch and uses the
    envelope only for the buzz.
  - Channel allocation: **A = lead, B = bass, C =** real drums if present
    (the harmony fills the rows between hits — drums and chords time-share the
    channel), else chord arps (`--arps`), else echo (`--echo`), else synth
    drums (chiptune), else harmony (faithful). GM kits map to the AY noise
    drums: kick, snare, and hi-hats — closed/pedal hats and rides tick short
    and quiet, open hats and crashes ring a sizzling tail; simultaneous hits
    collapse to the strongest (kick > snare > cymbals).
  - pattern dedup — identical 64-row patterns are stored once and replayed
    through the PT3 position list (repeats cost 1 byte, not a pattern).
- **`spectrumizer/ir.py`** — the source-agnostic note model both inputs target.

### PT3 invariants baked in (from the player source)

The player ends a pattern when **channel A** hits its `0x00` terminator and then
resets all three channels — so every channel of a pattern encodes **exactly**
`ROWS_PER_PATTERN` (64) rows, and row 0 is never an empty rest (the packer drops
leading rests). `arrange/model.py` enforces both.

## Listen to it (no Spectrum needed)

spectrumizer ships its own playback path: a small software **AY-3-8910** that
renders a `.pt3` to a stereo `.wav` (classic ABC panning — A left, B centre,
C right) and plays it through your system audio player (`afplay` on macOS;
`ffplay` / `aplay` / `paplay` / `sox` elsewhere).

```bash
spectrumizer-play song.pt3            # render song.wav and play it
spectrumizer-play song.pt3 --no-play  # just write the .wav
spectrumizer-play song.pt3 --seconds 30   # cap length, looping the song's tail
spectrumizer-play song.pt3 --rate 22050   # faster render (lower fidelity)
spectrumizer-play song.pt3 --tuning equal # equal-tempered instead of the PT3 table
spectrumizer-play song.pt3 --stereo mono  # mono (default abc = A-left/B-centre/C-right)
spectrumizer-play song.pt3 --noise-period 5  # force a noise period (default: the module's real one)
```

The synth (`spectrumizer/audio.py`) plus the PT3 interpreter
(`spectrumizer/pt3/player.py`, the inverse of the encoder) only implement the
subset of PT3 this tool emits — notes, OFF, sample/ornament/volume, NtSkip, and
the **AY hardware envelope** (all 16 R13 shapes, so buzzer-bass modules audition
too). Pointing it at a foreign module (full Vortex Tracker output) is detected,
not silent: it warns about tokens outside that subset and about a non-default
tone table. Pitch uses the **exact PT3 tone table** (the table-1 periods from the real Bulba player,
so notes land where the chip puts them; pass `--tuning equal` for the old
equal-tempered approximation). Treat it as a faithful **audition**, not a
cycle-exact emulation — for the real chip, package the `.pt3` for an emulator
(below).

## Hear it on a real Spectrum / emulator

A `.pt3` is only music data. `spectrumizer-pack` wraps it with Sergey Bulba's PT3
replayer + a tiny loader and assembles a **self-playing tape or snapshot** you
can load in Fuse / ZEsarUX (or on real hardware):

```bash
spectrumizer-pack song.pt3 -o song.tap     # autoloading tape (BASIC + CODE)
spectrumizer-pack song.pt3 --sna song.sna  # 128K snapshot (boots straight into the tune)
spectrumizer-pack song.pt3 --tap a.tap --sna a.sna   # both at once
```

The music uses the AY, so it needs a **128K** machine: the `.sna` is a 128K
snapshot and just plays; the `.tap` must be loaded in **128K / 128-BASIC** mode
(the 48K loader has no AY). Needs **sjasmplus** on PATH to assemble the player.
The bundled player is Bulba's, under its own terms — see [`LICENSING.md`](LICENSING.md).

While it plays, the program shows a small title screen — a colour-cycling
*spectrumizer* logo plus the module's **title and author**, read straight from
the PT3 header, with the ROM font on black.

## Get the notes back out (PT3 → MIDI)

The pipeline also runs in reverse: `spectrumizer-export` decodes a `.pt3` (with
the same interpreter the audition uses) and writes a standard MIDI file — to
study a module, edit it in a DAW, or re-spectrumize it after changes.

```bash
spectrumizer-export song.pt3              # → song.mid
spectrumizer-export song.pt3 --no-merge   # keep pattern-boundary re-attacks
```

What you get: channels **A/B/C as three tracks** at the module's effective
tempo, velocities from the AY volumes, percussive samples (one-shot noise
bursts) as **GM drums** — kick / snare / closed / open hat by noise colour —
and chord-arp ornaments **expanded back into the chords they fake** (an `--arps`
module exports real Am7 stacks, not a lone root). Notes the encoder re-attacked
at pattern boundaries are merged back into one held note — at the PT3 level a
re-attack and a genuinely repeated note are the same bytes there, so a repeated
note landing exactly on a boundary merges too; `--no-merge` keeps every attack.

What you don't: timbre. Samples, buzzer bass and noise periods have no MIDI
analogue, and a spectrumizer-made module returns the **3-channel arrangement**,
not your original source (the reduction is lossy by design; echo and octave
embellishments export as the notes they play). Foreign modules audition-grade
only: tokens outside the decoded subset are skipped with a warning. And the
usual reminder: exporting somebody's module to MIDI does **not** clear its
licence.

## Demos

Hear every mode in your browser on the **[demo page](https://revengator.github.io/spectrumizer/)**
(GitHub Pages, nothing to install) — or click a clip to play it in GitHub's file
viewer. All clips are the bundled public-domain examples rendered through the
built-in software AY: `ode-to-joy.mid` for most, `pachelbel-canon.mid` where a
low ground bass or chords shine (buzzer, arps), `korobeiniki.mid` (the Tetris
folk tune, with a real GM drum track) for the drums clip, and `greensleeves.mid`
(the traditional tune, harmonised with 7th/sus chords) for the arps-v2 clip.
Regenerate with `pip install -e ".[demos]" && python examples/make_demos.py`.

| Demo | What it shows |
|---|---|
| ▶ [Faithful](docs/audio/faithful.mp3) | 3-voice reduction |
| ▶ [Chiptune](docs/audio/chiptune.mp3) | octave lead + synth drums (off-beat hi-hats included) |
| ▶ [Chord arpeggios](docs/audio/arps.mp3) | triads faked on one channel via 50 Hz ornaments (`--arps`) |
| ▶ [Seventh & sus arpeggios](docs/audio/arps7.mp3) | Greensleeves: Am7 / Fmaj7 / G7 / Esus4 — four-note chords from one channel |
| ▶ [Echo](docs/audio/echo.mp3) | the lead repeated half a beat later, quieter (`--echo`) |
| ▶ [Vibrato](docs/audio/vibrato.mp3) | delayed sub-semitone vibrato, encoded inside the sample (`--vibrato`) |
| ▶ [Real drums + harmony](docs/audio/drums.mp3) | a GM drum track (kick/snare/hi-hats) and the chords time-sharing channel C |
| ▶ [Buzzer (pure)](docs/audio/buzzer.mp3) | bass = the AY hardware envelope, tone off (`--bass envelope`) |
| ▶ [Buzzer (tone+env)](docs/audio/buzzer-tone.mp3) | envelope buzz, tone keeps the pitch (`--bass envelope-tone`) |
| ▶ [No dynamics](docs/audio/chiptune-flat.mp3) | flat volume — vs the velocity dynamics |
| ▶ [Equal-tempered](docs/audio/chiptune-equal.mp3) | vs the exact PT3 tone table |
| ▶ [Mono](docs/audio/chiptune-mono.mp3) | vs the default ABC stereo |
| ▶ [Everything at once](docs/audio/combo.mp3) | the flags compose: octave lead + vibrato + buzzer bass + rippling arps (`--arp-speed 2`), an octave down |

Every demo also ships as an **executable 128K snapshot** in
[`docs/audio/`](docs/audio/) (`<demo>.sna`, made with `spectrumizer-pack`) —
load it in any Spectrum emulator to hear the real Z80 player instead of the
software AY. Demos that differ only in playback flags (`--tuning`, `--stereo`)
share `chiptune.sna`: those are audition-player options, not part of the module.

## Tests

```bash
pip install -e ".[dev]"     # installs pytest
pytest -q
```

## Status

- **Generate:** MIDI → PT3, faithful + chiptune, velocity-driven dynamics,
  **hi-hat percussion** (GM cymbals mapped, off-beat hats in the synth groove),
  **chord arpeggios** with the full triad/7th/sus vocabulary (`--arps`,
  `--arp-speed`), **echo** (`--echo`), **lead vibrato** (`--vibrato`),
  **auto-transpose** into the AY register (`--auto-transpose`), and
  **buzzer bass** through the AY hardware envelope (`--bass envelope` /
  `envelope-tone`).
- **Audition:** built-in software-AY playback to a stereo WAV — exact PT3 tone
  table, real per-frame noise period, ABC panning, and the AY **hardware
  envelope generator** (`spectrumizer-play` / `--play`).
- **Package:** wrap a `.pt3` (+ Bulba's replayer) into a self-playing `.tap` /
  128K `.sna` for an emulator or real hardware (`spectrumizer-pack`).
- **Export:** PT3 → MIDI — the reverse pipeline: decode a module back into
  notes and take them to a DAW (`spectrumizer-export`).

The feature set is complete — the project is maintained, not growing.

## Origin

spectrumizer grew out of hand-written, per-track PT3 composer scripts for a ZX
Spectrum game, generalising them into a single reusable arranger. It is now a
standalone, game-agnostic tool.

## Credits

- **Sergey Bulba** — the PT3 module format and the Vortex Tracker / PT3 replayer
  this tool targets, including the NoteTableCreator tone-table data the audition
  synth uses for exact Spectrum pitches.
- **Ivan Roshin** — NoteTableCreator, the source of those packed AY tone tables.

These credits acknowledge the format and reference data; spectrumizer's encoder,
decoder and synth are independent implementations (see [`LICENSE`](LICENSE)).

## Licence

[MIT](LICENSE) © Miguel Ángel Esteve Marco. Note: the MIT licence covers
**spectrumizer's own code**, not the music you run through it — see
[`LICENSING.md`](LICENSING.md).
