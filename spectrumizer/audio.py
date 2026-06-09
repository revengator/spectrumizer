"""AY-3-8910 synthesiser + WAV rendering for PT3 playback.

A deliberately small software AY: three square-wave tone generators, one 17-bit
LFSR noise generator, per-channel tone/noise mixing and a 16-level logarithmic
DAC. No envelope generator — spectrumizer's samples carry amplitude per tick, so
the envelope path is never used. The point is to *audition* a module on any
machine, not to be a cycle-exact emulator; pitch uses the exact PT3 tone table by
default (`build_pt3_table`), with an equal-tempered fallback (`tuning='equal'`).
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from array import array

from .pt3.player import Module, iter_frames, FRAME_HZ

# AY clock on the 128K / +2 (Hz). Tone freq = clock / (16 * period).
AY_CLOCK = 1773400
DEFAULT_RATE = 44100

# 16-level AY (not YM) DAC, normalised 0..1.
AY_VOL = [
    0.0, 0.00999, 0.01445, 0.02106, 0.03070, 0.04555, 0.06450, 0.10736,
    0.12659, 0.20499, 0.29221, 0.37284, 0.49253, 0.63532, 0.80558, 1.0,
]


# --- the exact PT3 tone table (the real Spectrum pitches) ---------------------
# Tone table #1 (the id the writer stamps), taken from the NoteTableCreator data
# in Sergey Bulba's PT3 player (`T_PACK`, first physical table): the 12 packed
# octave periods 0x06EC..0x0D10. The player stores them lowest-pitch first, so
# we reverse to put C (largest period) at index 0, then build the 8 octaves by
# the player's own successive /2 — `period(note) = base[note%12] >> note//12`.
# (The player's two ±1 end-corrections are sub-cent and omitted.)
PT3_T1_OCTAVE = [
    0x0D10, 0x0C55, 0x0BA4, 0x0AFC, 0x0A5F, 0x09CA,   # C  C# D  D# E  F
    0x093D, 0x08B8, 0x083B, 0x07C5, 0x0755, 0x06EC,   # F# G  G# A  A# B
]


def build_pt3_table() -> list:
    """The exact PT3 tone-table-1 periods for note indices 0..95 (0 == C-1)."""
    return [PT3_T1_OCTAVE[n % 12] >> (n // 12) for n in range(96)]


def build_equal_table(clock: int = AY_CLOCK) -> list:
    """Equal-tempered AY tone periods (A4=440) — the legacy approximation."""
    table = []
    for idx in range(96):
        freq = 440.0 * 2.0 ** ((idx + 24 - 69) / 12.0)   # idx 0 -> MIDI 24 (C1)
        table.append(max(1, min(4095, round(clock / (16.0 * freq)))))
    return table


_PT3_PERIOD = build_pt3_table()
_EQ_PERIOD = build_equal_table()


def render_pcm(module: Module, *, sample_rate: int = DEFAULT_RATE,
               loops: int = 1, max_seconds: float | None = None,
               noise_period: int | None = None, tuning: str = 'pt3',
               stereo: str = 'abc', separation: float = 0.7,
               gain: float = 0.9) -> tuple[array, int]:
    """Render a parsed module to 16-bit PCM; returns ``(pcm, channels)``.

    `tuning`: 'pt3' (default, the exact Spectrum tone table) or 'equal'.
    `noise_period`: None (default) tracks the module's real per-frame AY noise
    register (R6); pass 1..31 to force a fixed period.
    `stereo`: 'abc' (A-left / B-centre / C-right, the classic ZX layout), 'acb',
    or 'mono'. `separation`: 0..1 stereo width (0 = narrow, 1 = hard pan).
    """
    periods = _EQ_PERIOD if tuning == 'equal' else _PT3_PERIOD
    spf = sample_rate // FRAME_HZ                      # output samples per frame
    pcm = array('h')

    # Per-channel L/R panning weights for channels A, B, C.
    if stereo == 'mono':
        channels = 1
        pan_l = pan_r = (1.0, 1.0, 1.0)
        norm_l = norm_r = 1.0 / 3.0
    else:
        channels = 2
        sep = max(0.0, min(1.0, separation))
        pos = {'abc': ('L', 'C', 'R'), 'acb': ('L', 'R', 'C')}.get(stereo,
                                                                   ('L', 'C', 'R'))
        wl = {'L': 1.0, 'R': 1.0 - sep, 'C': 0.7071}
        wr = {'L': 1.0 - sep, 'R': 1.0, 'C': 0.7071}
        pan_l = tuple(wl[p] for p in pos)
        pan_r = tuple(wr[p] for p in pos)
        norm_l = 1.0 / max(1e-6, sum(pan_l))
        norm_r = 1.0 / max(1e-6, sum(pan_r))

    phase = [0.0, 0.0, 0.0]
    noise_acc = 0.0
    lfsr = 1
    noise_level = 1.0

    for frame, noise_r6 in iter_frames(module, loops=loops, max_seconds=max_seconds):
        # Precompute each channel's constant-per-frame parameters.
        ch = []
        for note_idx, amp, tone_on, noise_on in frame:
            if amp <= 0 or note_idx is None:
                ch.append(None)
                continue
            period = periods[note_idx] if 0 <= note_idx < 96 \
                else periods[max(0, min(95, note_idx))]
            inc = (AY_CLOCK / (16.0 * period)) / sample_rate
            ch.append((inc, AY_VOL[amp], tone_on, noise_on))

        # AY noise period this frame: the module-derived R6 (0 -> hardware 1),
        # or a fixed override. Recomputed per frame so it tracks the song.
        npd = noise_period if noise_period is not None else ((noise_r6 & 0x1F) or 1)
        noise_step = (AY_CLOCK / 16.0 / npd) / sample_rate

        for _s in range(spf):
            # advance the shared noise LFSR
            noise_acc += noise_step
            while noise_acc >= 1.0:
                noise_acc -= 1.0
                newbit = (lfsr ^ (lfsr >> 3)) & 1
                lfsr = (lfsr >> 1) | (newbit << 16)
                noise_level = float(lfsr & 1)

            left = right = 0.0
            for ci in range(3):
                c = ch[ci]
                if c is None:
                    continue
                inc, vol, tone_on, noise_on = c
                ph = phase[ci] + inc
                if ph >= 1.0:
                    ph -= int(ph)
                phase[ci] = ph
                t_eff = 1.0 if (not tone_on or ph < 0.5) else 0.0
                n_eff = 1.0 if (not noise_on or noise_level >= 1.0) else 0.0
                out = vol * t_eff * n_eff
                left += out * pan_l[ci]
                right += out * pan_r[ci]

            lv = int(left * norm_l * gain * 32767.0)
            pcm.append(-32768 if lv < -32768 else 32767 if lv > 32767 else lv)
            if channels == 2:
                rv = int(right * norm_r * gain * 32767.0)
                pcm.append(-32768 if rv < -32768 else 32767 if rv > 32767 else rv)

    return pcm, channels


def write_wav(path: str, pcm: array, sample_rate: int = DEFAULT_RATE,
              channels: int = 1) -> None:
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes() if hasattr(pcm, 'tobytes') else struct.pack(
            f'<{len(pcm)}h', *pcm))


# Players to try, in order; first one found on PATH wins.
_PLAYERS = (
    ('afplay', []),
    ('ffplay', ['-nodisp', '-autoexit', '-loglevel', 'quiet']),
    ('aplay', ['-q']),
    ('paplay', []),
    ('play', ['-q']),                  # SoX
)


def play_wav(path: str) -> bool:
    """Play a WAV with the first available system player. Returns success."""
    for exe, flags in _PLAYERS:
        found = shutil.which(exe)
        if found:
            subprocess.run([found, *flags, path], check=False)
            return True
    return False


def duration_seconds(module: Module, *, loops: int = 1,
                     max_seconds: float | None = None) -> float:
    """Total play length in seconds (cheap: sums rows, no synthesis)."""
    if max_seconds is not None:
        return float(max_seconds)
    speed = module.speed
    frames = 0
    from .pt3.player import _positions
    for pidx in _positions(module, loops, unbounded=False):
        if pidx < len(module.patterns):
            frames += max(len(c) for c in module.patterns[pidx]) * speed
    return frames / FRAME_HZ
