"""spectrumizer — generate ZX Spectrum AY (PT3) music from public sources.

Pipeline:  source -> IR (ir.Song) -> arrange (3 AY channels) -> PT3 bytes.

LICENCE GUARDRAIL: spectrumizer does NOT launder licences. The licence of the
SOURCE governs the OUTPUT. Only public-domain or your own material is safe to
bundle into a game. See LICENSING.md.
"""

from .ir import Song, Note

__all__ = ["Song", "Note"]
__version__ = "0.2.0"
