"""PT3 playback — read a spectrumizer-generated module back into musical events.

This is the inverse of `pt3.encode` / `pt3.writer`: it parses the small PT3
subset this package emits (notes, OFF, sample / ornament / volume changes,
NtSkip) and yields, frame by frame (50 Hz), the per-channel state needed to
drive an AY synthesiser (see `spectrumizer.audio`).

It is **not** a full Vortex Tracker player — it understands exactly the tokens
`encode_channel` writes plus the AY hardware-envelope tokens (so buzzer-bass
modules can be auditioned), and nothing else (no glissando, vibrato,
noise-period commands). That is enough to audition anything spectrumizer makes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FRAME_HZ = 50


@dataclass
class ParsedSample:
    """A PT3 instrument as per-tick timbre + loop point.

    Each tick is (tone_on, noise_on, amp, noise_path, noise_add, persist):
    the mixer gates, the amplitude, and the noise-period contribution — a tick
    on the noise path (byte1 bit7 == 0) drives the AY noise register by
    ``byte0 >> 1`` (+ a persisted slide if byte1 bit5 is set).
    """
    loop: int
    ticks: list  # list[tuple[bool, bool, int, bool, int, bool]]

    def at(self, pos: int):
        return self.ticks[pos] if pos < len(self.ticks) else self.ticks[-1]

    def advance(self, pos: int) -> int:
        pos += 1
        return pos if pos < len(self.ticks) else self.loop


@dataclass
class ParsedOrnament:
    """A PT3 ornament as signed semitone offsets + loop point."""
    loop: int
    offsets: list  # list[int]

    def at(self, pos: int) -> int:
        return self.offsets[pos] if pos < len(self.offsets) else self.offsets[-1]

    def advance(self, pos: int) -> int:
        pos += 1
        return pos if pos < len(self.offsets) else self.loop


@dataclass
class RowEvent:
    """An onset on one row: a note (or a note-cut) plus the active timbre."""
    note: int | None     # PT3 note byte (0x50..0xAF), or None for OFF (note cut)
    sample: int
    ornament: int
    vol: int
    env: tuple | None = None   # (shape 1..14, period 0..65535) or None (env off)
    env_retrig: bool = False   # this event (re)wrote R13 -> the AY retriggers


@dataclass
class Module:
    speed: int
    loop_pos: int
    order: list             # pattern indices, in play order
    patterns: list          # per pattern: (chA, chB, chC), each list[RowEvent|None]
    samples: dict           # slot -> ParsedSample
    ornaments: dict         # slot -> ParsedOrnament
    name: str = ""
    author: str = ""


# --- the default timbres, parsed once so a header with addr 0 still plays ---
_DEFAULT_SAMPLE_FALLBACK = ParsedSample(0, [(True, False, 12, False, 0, False)])
_DEFAULT_ORNAMENT_FALLBACK = ParsedOrnament(0, [0])


def _u16(data: bytes, off: int) -> int:
    return data[off] | (data[off + 1] << 8)


def _mixer(b1: int) -> tuple[bool, bool]:
    """Decode a sample tick's byte1 mixer bits into (tone_on, noise_on).

    The real player's mixer is negative logic (CHREGS: ``RRA / AND #48``):
    byte1 bit4 disables the tone, bit7 disables the noise. So 0x80 -> tone only,
    0x10 -> noise only, 0x00 -> both, 0x90 -> neither (the buzzer mix: the
    channel is then heard only through the hardware envelope).
    """
    return not (b1 & 0x10), not (b1 & 0x80)


def parse_sample(data: bytes, addr: int) -> ParsedSample:
    loop = data[addr]
    length = data[addr + 1] + 1
    ticks = []
    p = addr + 2
    for _ in range(length):
        b0, b1 = data[p], data[p + 1]
        tone_on, noise_on = _mixer(b1)
        noise_path = (b1 & 0x80) == 0     # bit7=0 -> this tick drives the noise period
        noise_add = (b0 >> 1) & 0xFF      # byte0 -> AddToNs contribution
        persist = (b1 & 0x20) != 0        # bit5 -> persist the noise slide (CrNsSl)
        ticks.append((tone_on, noise_on, b1 & 0x0F, noise_path, noise_add, persist))
        p += 4
    return ParsedSample(min(loop, length - 1), ticks)


def parse_ornament(data: bytes, addr: int) -> ParsedOrnament:
    loop = data[addr]
    length = data[addr + 1] + 1
    offs = []
    p = addr + 2
    for _ in range(length):
        v = data[p]
        offs.append(v - 256 if v >= 128 else v)   # signed semitone offset
        p += 1
    return ParsedOrnament(min(loop, length - 1), offs)


def decode_channel(data: bytes, addr: int) -> list:
    """Decode one packed channel into a per-row list of RowEvent | None.

    Mirrors the token grammar emitted by `encode_channel`. A note/OFF event
    occupies `cur_skip` rows; the extra rows are None (held / silent).
    """
    rows: list = []
    cur_sample, cur_orn, cur_vol, cur_skip = 1, 0, 15, 1
    cur_env = None                          # (shape, period) or None (env off)
    cur_env_retrig = False                  # set when an env token (re)wrote R13
    i = addr
    n = len(data)
    while i < n:
        b = data[i]; i += 1
        if b == 0x00:                       # end of channel
            break
        if 0xF0 <= b <= 0xFF:               # first-note preamble (orn + sample*2)
            cur_orn = b & 0x0F
            cur_sample = data[i] // 2; i += 1
            continue
        if 0xD0 <= b <= 0xEF:               # sample change
            cur_sample = b & 0x1F
            continue
        if 0x40 <= b <= 0x4F:               # ornament change
            cur_orn = b & 0x0F
            continue
        if b == 0xB0:                       # envelope OFF
            cur_env, cur_env_retrig = None, True
            continue
        if b == 0xB1:                       # NtSkip change
            cur_skip = data[i]; i += 1
            continue
        if 0xB2 <= b <= 0xBF:               # set envelope: shape + period (hi, lo)
            shape = b - 0xB1                # 1..14 (0xB0 is OFF, 0xB1 is NtSkip)
            period = (data[i] << 8) | data[i + 1]; i += 2
            cur_env, cur_env_retrig = (shape, period), True
            continue
        if 0xC1 <= b <= 0xCF:               # volume change
            cur_vol = b & 0x0F
            continue
        if b == 0xC0:                       # OFF (note cut)
            rows.append(RowEvent(None, cur_sample, cur_orn, cur_vol,
                                 cur_env, cur_env_retrig))
            rows.extend([None] * (cur_skip - 1))
            cur_env_retrig = False
            continue
        if 0x50 <= b <= 0xAF:               # note
            rows.append(RowEvent(b, cur_sample, cur_orn, cur_vol,
                                 cur_env, cur_env_retrig))
            rows.extend([None] * (cur_skip - 1))
            cur_env_retrig = False
            continue
        # any other token: ignore (no time cost)
    return rows


def parse_module(data: bytes) -> Module:
    """Parse a spectrumizer-generated PT3 module into a playable `Module`."""
    if data[:13] != b'ProTracker 3.':
        raise ValueError("not a ProTracker 3 module")
    speed = data[0x64] or 6
    loop_pos = data[0x66]
    ppt_off = _u16(data, 0x67)

    samples = {}
    for slot in range(32):
        a = _u16(data, 0x69 + slot * 2)
        if a:
            samples[slot] = parse_sample(data, a)
    ornaments = {}
    for slot in range(16):
        a = _u16(data, 0xA9 + slot * 2)
        if a:
            ornaments[slot] = parse_ornament(data, a)

    order = []
    p = 0xC9
    while p < len(data) and data[p] != 0xFF:
        order.append(data[p] // 3)
        p += 1

    n_pat = (max(order) + 1) if order else 0
    patterns = []
    for idx in range(n_pat):
        base = ppt_off + idx * 6
        a, b, c = _u16(data, base), _u16(data, base + 2), _u16(data, base + 4)
        patterns.append((decode_channel(data, a),
                         decode_channel(data, b),
                         decode_channel(data, c)))

    name = data[0x1E:0x3E].decode('ascii', 'replace').rstrip()
    author = data[0x42:0x62].decode('ascii', 'replace').rstrip()
    return Module(speed, loop_pos, order, patterns, samples, ornaments, name, author)


@dataclass
class _Chan:
    note: int | None = None      # base PT3 note byte
    active: bool = False
    sample: int = 1
    ornament: int = 0
    vol: int = 15
    s_pos: int = 0
    o_pos: int = 0
    cr_ns_sl: int = 0            # persisted noise slide (CrNsSl)
    env: tuple | None = None     # (shape, period) while this channel uses the env


def _positions(module: Module, loops: int, unbounded: bool):
    """Yield pattern indices in play order: one full pass, then repeat the
    `loop_pos`-onward tail (loops-1 more times, or forever if unbounded)."""
    yield from module.order
    tail = module.order[module.loop_pos:] or module.order
    if unbounded:
        while True:
            yield from tail
    else:
        for _ in range(max(0, loops - 1)):
            yield from tail


def iter_frames(module: Module, *, loops: int = 1, max_seconds: float | None = None):
    """Yield, per 50 Hz frame, ``(channels, noise_period, envelope)``.

    `channels` is a list of 3 tuples
    ``(note_index | None, amplitude 0..15, tone_on, noise_on, use_env)`` —
    `note_index` is the semitone index (0 == PT3 C-1) after the ornament offset,
    amplitude already folds the channel volume into the sample amplitude, and
    `use_env` is True while that channel is driven by the AY hardware envelope
    (its amplitude is then ignored — the envelope level is used instead).

    `noise_period` is the AY noise register R6 the real player would write this
    frame: ``Ns_Base + AddToNs`` (0..255; the chip uses the low 5 bits, and 0
    means hardware period 1). `Ns_Base` is only changed by the PD_NOIS pattern
    command — which spectrumizer never emits — so for its own modules the noise
    period is whatever the active samples' byte0 dictates (0 by default).

    `envelope` is ``(period, shape, retrig)`` — the AY's single envelope
    generator (R11/R12 period, R13 shape 1..14). `retrig` is True only on the
    first frame of a row that (re)wrote R13, mirroring the real player (which
    parks R13 at a no-write sentinel otherwise, so the envelope free-runs). If
    several channels enable the envelope, the highest channel's period/shape win.
    """
    speed = module.speed
    budget = None if max_seconds is None else int(max_seconds * FRAME_HZ)
    emitted = 0
    chans = [_Chan(), _Chan(), _Chan()]
    ns_base = 0          # set only by PD_NOIS (not in spectrumizer's token subset)
    add_to_ns = 0        # global noise add; persists across frames like the player

    for pidx in _positions(module, loops, unbounded=max_seconds is not None):
        if pidx >= len(module.patterns):
            continue
        chan_rows = module.patterns[pidx]
        rows = max(len(c) for c in chan_rows)
        for r in range(rows):
            row_retrig = False
            for ci in range(3):
                seq = chan_rows[ci]
                ev = seq[r] if r < len(seq) else None
                if ev is None:
                    continue
                cs = chans[ci]
                if ev.env_retrig:                   # an env token (re)set state
                    cs.env = ev.env                 # else sticky (persists, like
                    row_retrig = True               # the real player's Env_En)
                if ev.note is None:                 # OFF
                    cs.active = False
                else:
                    cs.note, cs.active = ev.note, True
                    cs.sample, cs.ornament, cs.vol = ev.sample, ev.ornament, ev.vol
                    cs.s_pos = cs.o_pos = 0
            # the AY has a single envelope generator: the highest channel that
            # currently uses it wins its period/shape.
            env_ps = next((c.env for c in reversed(chans) if c.env is not None), None)
            env_shape = env_ps[0] if env_ps else 0
            env_period = env_ps[1] if env_ps else 0
            for _f in range(speed):
                frame = []
                for ci in range(3):              # A, B, C order: last noise tick wins
                    cs = chans[ci]
                    if not cs.active or cs.note is None:
                        frame.append((None, 0, False, False, False))
                        continue
                    samp = module.samples.get(cs.sample, _DEFAULT_SAMPLE_FALLBACK)
                    orn = module.ornaments.get(cs.ornament, _DEFAULT_ORNAMENT_FALLBACK)
                    tone_on, noise_on, s_amp, noise_path, noise_add, persist = \
                        samp.at(cs.s_pos)
                    note_idx = (cs.note - 0x50) + orn.at(cs.o_pos)
                    amp = (s_amp * cs.vol) // 15
                    frame.append((note_idx, amp, tone_on, noise_on, cs.env is not None))
                    if noise_path:               # this tick drives the AY noise period
                        add_to_ns = (noise_add + cs.cr_ns_sl) & 0xFF
                        if persist:
                            cs.cr_ns_sl = add_to_ns
                    cs.s_pos = samp.advance(cs.s_pos)
                    cs.o_pos = orn.advance(cs.o_pos)
                env = (env_period, env_shape, row_retrig and _f == 0)
                yield frame, (ns_base + add_to_ns) & 0xFF, env
                emitted += 1
                if budget is not None and emitted >= budget:
                    return
