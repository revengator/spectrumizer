# Licensing — read before bundling anything spectrumizer produces

spectrumizer is a **format converter**. It does not change, grant, or launder any
rights. **The licence of the source you feed in governs the `.pt3` it spits out.**

A `.pt3` generated from a copyrighted MIDI is a **derivative work** of that
copyrighted composition — still copyrighted. Re-encoding it for the AY chip does
not make it free to ship.

> This is about the **music** you convert. spectrumizer's *own code* is MIT —
> see [`LICENSE`](LICENSE).

## What is safe to bundle into a game / release

1. **Public-domain compositions.** The *composition* must be PD (e.g. classical
   works whose composer died long enough ago — Holst's *The Planets*, Grieg, etc.).
   Note: a *specific recording/arrangement* can be protected even when the
   underlying composition is PD — so arrange it yourself (which is exactly what
   spectrumizer does from the notes), don't convert someone's protected MIDI
   arrangement verbatim if that arrangement is itself creative and protected.
2. **Your own original material.** Compose it (MIDI/score) and convert it.
3. **Explicitly licensed material**, where the licence permits redistribution and
   derivative works, and the licence terms are honoured.

## What is NOT safe

- A MIDI of a modern song / film score / game soundtrack downloaded from the web.
  Converting it to PT3 does not clear the rights. Do not ship it.
- "Style homages" are fine only when they are genuinely **original compositions**
  in the style of X — style/meter/instrumentation are not copyrightable, but a
  recognisable melody is.

## Rule of thumb

**Verify each track's licence BEFORE bundling**, and never relax your project's
own licence to paper over a missing permission on an asset. When in doubt, leave
it out — or replace it with an original or PD piece.
