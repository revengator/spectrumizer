# spectrumizer

[![PyPI](https://img.shields.io/pypi/v/spectrumizer.svg)](https://pypi.org/project/spectrumizer/)
[![CI](https://github.com/revengator/spectrumizer/actions/workflows/ci.yml/badge.svg)](https://github.com/revengator/spectrumizer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Live demos](https://img.shields.io/badge/%E2%96%B6-live%20demos-brightgreen.svg)](https://revengator.github.io/spectrumizer/)

Generate **ZX Spectrum AY music (`.pt3`)** from public sources (MIDI now;
MusicXML/scores planned). The output is a standard Vortex Tracker / Sergey
Bulba PT3 module, so anything it produces drops straight into a Spectrum game
that ships a PT3 replayer.

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
pip install spectrumizer    # from PyPI — installs spectrumizer / spectrumizer-play / spectrumizer-pack
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

# chiptune flavour: octave-doubled leads + synth drums when the source has none
spectrumizer song.mid -o song.pt3 --style chiptune

# tune the AY octave by ear, change grid/tempo
spectrumizer song.mid --transpose -12 --rows-per-beat 4 --speed 6 \
    --name "MY THEME" --author "ME"

# dynamics: MIDI velocity drives per-note volume (on by default)
spectrumizer song.mid -o song.pt3 --no-dynamics      # ...or flat per-channel volume

# buzzer bass: drive the bass through the AY hardware envelope
spectrumizer song.mid --bass envelope        # pure buzzer — envelope is the oscillator (deep, coarse pitch)
spectrumizer song.mid --bass envelope-tone   # tone keeps the pitch, envelope adds the buzz (any register)

# chord arpeggios: channel C plays each chord's root and cycles a major/minor
# ornament at 50 Hz — one channel implies the whole triad (the classic AY trick)
spectrumizer song.mid --arps

# echo: channel C repeats the lead half a beat later, quieter (the other classic)
spectrumizer song.mid --echo

# generate and immediately hear it (renders through a software AY, then plays)
spectrumizer song.mid -o song.pt3 --play
```

Run `spectrumizer --help` for all flags.

## How it works

```
MIDI ─(inputs/midi.py, mido)→ IR ─(arrange/)→ 3 AY channels ─(pt3/)→ .pt3
```

- **`spectrumizer/pt3/`** — the proven PT3 emitter (note encoding, channel packer,
  samples, ornaments, file writer). The byte format is verified against the real
  player; don't change it blindly.
- **`spectrumizer/arrange/`** — the hard part:
  - `quantize` — map time to PT3's row grid (derive `speed` from tempo).
  - `reduce` — peel the source polyphony into ≤3 monophonic lines (lead / bass /
    harmony) via a greedy high/low "skyline".
  - `embellish` — extra voices: octave leads + synth drums (chiptune style),
    **chord arpeggios** (`--arps`) — each source chord becomes its root note plus
    a major/minor ornament cycling 0/+4/+7 (or 0/+3/+7) semitones at 50 Hz, so
    one AY channel implies the full triad (`arrange/chords.py` recognises the
    triads) — and **echo** (`--echo`) — the lead repeated half a beat later,
    quieter, on channel C.
  - dynamics — MIDI velocity → per-note AY volume, normalised so the piece's
    loudest note hits each channel's ceiling (on by default; `--no-dynamics`).
  - buzzer bass — `--bass envelope` routes channel B through the AY **hardware
    envelope** at each note's pitch (the deep AY buzzer; pitch is coarse, best
    low). `--bass envelope-tone` keeps the tone for exact pitch and uses the
    envelope only for the buzz.
  - Channel allocation: **A = lead, B = bass, C =** real drums if present, else
    chord arps (`--arps`), else echo (`--echo`), else synth drums (chiptune),
    else harmony (faithful).
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
too). Pitch uses the **exact PT3 tone table** (the table-1 periods from the real Bulba player,
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

## Demos

Hear every mode in your browser on the **[demo page](https://revengator.github.io/spectrumizer/)**
(GitHub Pages, nothing to install) — or click a clip to play it in GitHub's file
viewer. Most are `examples/ode-to-joy.mid` rendered through the built-in software
AY; the buzzer clips use `examples/pachelbel-canon.mid` (its low ground bass is
where envelope bass shines). Regenerate with `pip install -e ".[demos]" && python examples/make_demos.py`.

| Demo | What it shows |
|---|---|
| ▶ [Faithful](docs/audio/faithful.mp3) | 3-voice reduction |
| ▶ [Chiptune](docs/audio/chiptune.mp3) | octave lead + synth drums |
| ▶ [Chord arpeggios](docs/audio/arps.mp3) | triads faked on one channel via 50 Hz ornaments (`--arps`) |
| ▶ [Echo](docs/audio/echo.mp3) | the lead repeated half a beat later, quieter (`--echo`) |
| ▶ [Buzzer (pure)](docs/audio/buzzer.mp3) | bass = the AY hardware envelope, tone off (`--bass envelope`) |
| ▶ [Buzzer (tone+env)](docs/audio/buzzer-tone.mp3) | envelope buzz, tone keeps the pitch (`--bass envelope-tone`) |
| ▶ [No dynamics](docs/audio/chiptune-flat.mp3) | flat volume — vs the velocity dynamics |
| ▶ [Equal-tempered](docs/audio/chiptune-equal.mp3) | vs the exact PT3 tone table |
| ▶ [Mono](docs/audio/chiptune-mono.mp3) | vs the default ABC stereo |
| ▶ [Everything at once](docs/audio/combo.mp3) | the flags compose: octave lead + buzzer bass + arps, an octave down |

## Tests

```bash
pip install -e ".[dev]"     # installs pytest
pytest -q
```

## Status

- **Generate:** MIDI → PT3, faithful + chiptune, velocity-driven dynamics,
  **chord arpeggios** (`--arps`), **echo** (`--echo`), and **buzzer bass**
  through the AY hardware envelope (`--bass envelope` / `envelope-tone`).
- **Audition:** built-in software-AY playback to a stereo WAV — exact PT3 tone
  table, real per-frame noise period, ABC panning, and the AY **hardware
  envelope generator** (`spectrumizer-play` / `--play`).
- **Package:** wrap a `.pt3` (+ Bulba's replayer) into a self-playing `.tap` /
  128K `.sna` for an emulator or real hardware (`spectrumizer-pack`).
- **Planned:**
  - **Drums + harmony multiplexed on channel C** — drum hits last one row, so
    the harmony can fill the gaps instead of being dropped when a song has drums.
  - **Sample vibrato/detune** — PT3 samples carry per-tick tone offsets
    (unused so far): sub-semitone vibrato for the lead, free at the sample level.
  - **Richer percussion** — hi-hats (GM 42/44/46) and synth-drum pattern
    variety beyond the fixed 4/4 backbeat.
  - **Arps v2** — 7th/sus ornaments, configurable arpeggio speed.
  - **MIDI tempo map** — honour tempo changes (today only the first
    `set_tempo` counts).
  - **Pattern deduplication** — store identical patterns once and repeat them
    in the position list (the writer already supports `order`).
  - **Auto-transpose** — fit the piece's range to the AY instead of tuning by ear.
  - MusicXML (music21) input · PT3 slides/glissando in the audition player ·
    raw-AY register-dump export (`.psg` / `.vtx`).

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
