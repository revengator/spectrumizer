"""PT3 instrument samples.

A PT3 "sample" is a per-tick amplitude/mixer envelope. Each tick is 4 bytes:
  byte0 = 0x00            (no amp-slide / no envelope / no noise-slide)
  byte1 = mix bits | amp  (bit7=1 tone OFF... see below)  amp = 0..15
  byte2 = tone offset lo  (0x00)
  byte3 = tone offset hi  (0x00)
Mixer bits in byte1 (per the player's mixer cascade):
  0x80 -> tone ON only      (noise off)
  0x10 -> noise ON only     (tone off)
  0x00 -> tone + noise      (percussive attack)
Sample header = [loop_point, length-1] then the ticks.

Distilled from a hand-written PT3 composer into a small named instrument
library. The byte1 mix semantics are confirmed against the real player.
"""

from __future__ import annotations


def _sample_raw(b1_ticks: list[int], loop: int | None = None) -> bytes:
    n = len(b1_ticks)
    loop = n - 1 if loop is None else loop
    out = bytearray()
    out.append(loop)
    out.append(n - 1)
    for b1 in b1_ticks:
        out.append(0x00)        # byte0: no amp-slide / env / noise-slide
        out.append(b1)          # byte1: mix bits | amplitude
        out.append(0x00)        # tone offset lo
        out.append(0x00)        # tone offset hi
    return bytes(out)


def build_lead() -> bytes:
    """Lead voice: tone only, soft attack-decay then steady sustain."""
    amps = [15, 15, 14, 14, 13, 13, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12]
    return _sample_raw([0x80 | a for a in amps])


def build_bass() -> bytes:
    """Bass / timpani-ish: percussive noise+tone attack, tone decay to a held
    low tail (loops on the tail so sustained bass notes ring)."""
    ticks = [0x00 | 0xF, 0x00 | 0xD,                          # noise+tone attack
             0x80 | 0xC, 0x80 | 0xA, 0x80 | 0x8, 0x80 | 0x6,  # tone decay
             0x80 | 0x5, 0x80 | 0x4, 0x80 | 0x3,
             0x80 | 0x2, 0x80 | 0x2, 0x80 | 0x2,
             0x80 | 0x2, 0x80 | 0x2, 0x80 | 0x2, 0x80 | 0x2]  # low tail (loop)
    return _sample_raw(ticks, loop=15)


def build_harmony() -> bytes:
    """Inner-voice pad: tone only, a touch softer than the lead, gentle decay
    to a quiet sustain so chords sit under the melody."""
    amps = [12, 12, 11, 11, 10, 10, 10, 9, 9, 9, 9, 9, 9, 9, 9, 9]
    return _sample_raw([0x80 | a for a in amps])


def build_snare() -> bytes:
    """Snare: pure-noise burst, fast decay to silence (loops silent)."""
    ticks = [0x10 | 0xF, 0x10 | 0xA, 0x10 | 0x6, 0x10 | 0x3,
             0x10 | 0x1, 0x10 | 0x0, 0x10 | 0x0, 0x10 | 0x0]
    return _sample_raw(ticks, loop=7)


def build_kick() -> bytes:
    """Kick: short noise+tone thud, tone decay to silence (loops silent)."""
    ticks = [0x00 | 0xF, 0x00 | 0xC, 0x80 | 0x9, 0x80 | 0x6,
             0x80 | 0x3, 0x80 | 0x1, 0x80 | 0x0, 0x80 | 0x0]
    return _sample_raw(ticks, loop=7)


# Canonical sample slot assignment used by the arranger / writer.
S_LEAD, S_BASS, S_HARMONY, S_SNARE, S_KICK = 1, 2, 3, 4, 5

DEFAULT_SAMPLES: dict[int, bytes] = {
    S_LEAD: build_lead(),
    S_BASS: build_bass(),
    S_HARMONY: build_harmony(),
    S_SNARE: build_snare(),
    S_KICK: build_kick(),
}
