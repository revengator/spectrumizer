"""PT3 instrument samples.

A PT3 "sample" is a per-tick amplitude/mixer envelope. Each tick is 4 bytes:
  byte0 = noise period<<1 on noise ticks (AddToNs -> R6); 0 elsewhere
  byte1 = mix bits | amp  (bit7=1 tone OFF... see below)  amp = 0..15
  byte2 = tone offset lo  \\ signed 16-bit, added to the note's tone period
  byte3 = tone offset hi  /  every tick (positive = flatter); byte1 bit6
                             makes it accumulate (CHP.TnAcc) — unused here
Mixer bits in byte1 (negative logic, per the real player's CHREGS):
  bit4 (0x10) disables the tone, bit7 (0x80) disables the noise. So
  0x80 -> tone only, 0x10 -> noise only, 0x00 -> tone + noise (percussive
  attack), 0x90 -> neither (the buzzer mix: heard only via the envelope).
Sample header = [loop_point, length-1] then the ticks.

Distilled from a hand-written PT3 composer into a small named instrument
library. The byte semantics are confirmed against the real player (CHREGS:
the tick's word at bytes 2-3 is popped into HL and ADDed to the tone period).
"""

from __future__ import annotations

# AY noise periods (R6, 0..31) for the drums: lower = brighter/hissier.
SNARE_NOISE = 6      # bright hiss with some body
KICK_NOISE = 20      # dark, thuddy


def _sample_raw(ticks: list, loop: int | None = None) -> bytes:
    """ticks: byte1 mix|amp values, or (byte1, noise_period[, tone_offset])
    tuples.

    The noise period is packed into byte0 (the player reads AddToNs =
    byte0 >> 1 into R6) and must only be set on ticks whose mixer enables
    the noise — with the noise off (byte1 bit7 = 1) the real player reads
    byte0 as an envelope slide instead. The tone offset is a signed period
    delta applied while the tick plays (bytes 2-3)."""
    n = len(ticks)
    loop = n - 1 if loop is None else loop
    out = bytearray()
    out.append(loop)
    out.append(n - 1)
    for t in ticks:
        b1, noise, tone = (t, 0, 0) if not isinstance(t, tuple) else \
            (t if len(t) == 3 else (*t, 0))
        out.append((noise & 0x1F) << 1)   # byte0: AddToNs, packed << 1
        out.append(b1)                    # byte1: mix bits | amplitude
        out.append(tone & 0xFF)           # bytes 2-3: signed tone offset,
        out.append((tone >> 8) & 0xFF)    #   little-endian
    return bytes(out)


def build_lead() -> bytes:
    """Lead voice: tone only, soft attack-decay then steady sustain."""
    amps = [15, 15, 14, 14, 13, 13, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12]
    return _sample_raw([0x80 | a for a in amps])


def build_lead_vibrato() -> bytes:
    """Lead with delayed vibrato: the lead's attack/decay, then the sustain
    loops an 8-tick triangle of tone-period offsets (6.25 Hz at 50 ticks/s;
    ±3 period units ≈ 12-25 cents around octaves 4-5 — subtle, vocal). The
    offsets ride in sample bytes 2-3, so the vibrato is free at the pattern
    level."""
    attack = [0x80 | a for a in (15, 15, 14, 14, 13, 13, 12, 12)]
    wave = [(0x80 | 12, 0, t) for t in (0, 2, 3, 2, 0, -2, -3, -2)]
    return _sample_raw(attack + wave, loop=8)


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
    """Snare: pure-noise burst at a mid noise period (hiss with some body
    instead of the harsh period-1 maximum), fast decay to silence (loops
    silent)."""
    amps = [0xF, 0xA, 0x6, 0x3, 0x1, 0x0, 0x0, 0x0]
    return _sample_raw([(0x10 | a, SNARE_NOISE) for a in amps], loop=7)


def build_kick() -> bytes:
    """Kick: short noise+tone thud with a deep (dark) noise period, tone
    decay to silence (loops silent)."""
    ticks = [(0x00 | 0xF, KICK_NOISE), (0x00 | 0xC, KICK_NOISE),
             0x80 | 0x9, 0x80 | 0x6,
             0x80 | 0x3, 0x80 | 0x1, 0x80 | 0x0, 0x80 | 0x0]
    return _sample_raw(ticks, loop=7)


def build_buzzer() -> bytes:
    """Pure buzzer bass: tone AND noise disabled (0x90), so the channel is heard
    purely through the AY hardware envelope — the envelope IS the oscillator.
    byte0 = 0 keeps the envelope enabled every tick; the pattern's envelope token
    (set per note at the right period) supplies the pitch and `Env_En`. A single
    looping tick — the envelope shape, not the sample, is the waveform. The
    characteristic deep AY buzzer, but with coarse pitch (best in low octaves)."""
    return _sample_raw([0x90], loop=0)


def build_buzzer_tone() -> bytes:
    """Tone+envelope buzzer: tone ON, noise off (0x80). The tone generator
    carries the exact pitch (R0/R1 = note) while the hardware envelope shapes it
    into a buzz — pitch-accurate at any register, a less 'pure' but more robust
    buzzer. Amplitude is taken from the envelope (Env_En), so the byte1 nibble is
    moot. One looping tick."""
    return _sample_raw([0x80], loop=0)


# Canonical sample slot assignment used by the arranger / writer.
(S_LEAD, S_BASS, S_HARMONY, S_SNARE, S_KICK,
 S_BUZZER, S_BUZZER_TONE, S_LEAD_VIB) = 1, 2, 3, 4, 5, 6, 7, 8

DEFAULT_SAMPLES: dict[int, bytes] = {
    S_LEAD: build_lead(),
    S_BASS: build_bass(),
    S_HARMONY: build_harmony(),
    S_SNARE: build_snare(),
    S_KICK: build_kick(),
    S_BUZZER: build_buzzer(),
    S_BUZZER_TONE: build_buzzer_tone(),
    S_LEAD_VIB: build_lead_vibrato(),
}
