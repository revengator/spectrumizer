"""Package a .pt3 module into a self-playing ZX Spectrum tape / snapshot.

A `.pt3` is only music data; to hear it on a real Spectrum (or an emulator) it
has to be wrapped with a PT3 replayer. This bundles Sergey Bulba's PT3 player
(`pt3player.asm`) + a tiny IM1 loader around the module and assembles the lot
with **sjasmplus**, producing:

  * a `.tap`  — an autoloading tape (BASIC loader + CODE), built here so the
    bytes are exact; load it on a **128K** machine (128 BASIC) so the AY is present.
  * a `.sna`  — a 128K snapshot (PC at the loader); the most reliable "just
    works with sound" option, since it boots straight into 128K state.

The Bulba player is bundled under its own terms (see ../../LICENSING.md), not
spectrumizer's MIT licence.

CLI: ``spectrumizer-pack song.pt3 -o song.tap`` (and/or ``--sna song.sna``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ORG = 0x8000                 # load address (uncontended RAM, protected by CLEAR)
MEM_TOP = 0xC000             # code + module + stack must stay below the paged bank
HERE = os.path.dirname(os.path.abspath(__file__))
PLAYER_ASM = os.path.join(HERE, "pt3player.asm")

# --- ZX Spectrum BASIC tokens for the tape autoloader ------------------------
_CLEAR, _LOAD, _CODE, _RANDOMIZE, _USR, _VAL = 0xFD, 0xEF, 0xAF, 0xF9, 0xC0, 0xB0


def _wrapper_asm(player_asm: str, pt3_path: str, *, sna: str | None,
                 raw_bin: str) -> str:
    """The sjasmplus source: IM1 loader + Bulba player + the module."""
    save_sna = f'    SAVESNA "{sna}", main\n' if sna else ""
    return f"""\
    DEVICE ZXSPECTRUM128
    ORG ${ORG:04X}
main:
    di
    ld sp, stacktop
    ld hl, module
    call START+3            ; init player with module address in HL
    ei
.loop:
    halt                    ; wait for the 50 Hz interrupt (IM1, ROM handler)
    call START+5            ; play one frame
    jr .loop

    include "{player_asm}"
module:
    incbin "{pt3_path}"
    ds 256                  ; stack lives in our own (CLEAR-protected) image
stacktop:
prog_end:
    SAVEBIN "{raw_bin}", main, prog_end - main
{save_sna}"""


def _tap_block(flag: int, data: bytes) -> bytes:
    body = bytes([flag]) + data
    chk = 0
    for b in body:
        chk ^= b
    body += bytes([chk])
    return len(body).to_bytes(2, "little") + body


def _tap_header(type_: int, name: str, length: int, p1: int, p2: int) -> bytes:
    h = (bytes([type_]) + name.encode("ascii", "replace")[:10].ljust(10)
         + length.to_bytes(2, "little") + p1.to_bytes(2, "little")
         + p2.to_bytes(2, "little"))
    return _tap_block(0x00, h)


def _basic_loader(code_addr: int) -> bytes:
    """`10 CLEAR VAL"addr-1": LOAD ""CODE: RANDOMIZE USR VAL"addr"` as line bytes.

    VAL"n" keeps the numbers as text (no 5-byte float embedding)."""
    def num(n: int) -> bytes:
        return bytes([_VAL, 0x22]) + str(n).encode() + bytes([0x22])
    line = (bytes([_CLEAR]) + num(code_addr - 1) + b":"
            + bytes([_LOAD, 0x22, 0x22, _CODE]) + b":"
            + bytes([_RANDOMIZE, _USR]) + num(code_addr) + bytes([0x0D]))
    return (10).to_bytes(2, "big") + len(line).to_bytes(2, "little") + line


def _build_tap(bin_bytes: bytes, name: str, org: int = ORG) -> bytes:
    prog = _basic_loader(org)
    return (_tap_header(0, name, len(prog), 10, len(prog)) + _tap_block(0xFF, prog)
            + _tap_header(3, name, len(bin_bytes), org, 0x8000)
            + _tap_block(0xFF, bin_bytes))


def pack(pt3_path: str, *, tap: str | None = None, sna: str | None = None,
         name: str | None = None) -> list[str]:
    """Wrap `pt3_path` into the requested `.tap` / `.sna`; return paths written.

    Raises RuntimeError on a missing sjasmplus, an assembly failure, or a module
    too large to fit under the paged bank.
    """
    if not tap and not sna:
        raise ValueError("nothing to do: pass tap= and/or sna=")
    with open(pt3_path, "rb") as f:
        data = f.read()
    if data[:13] != b"ProTracker 3.":
        raise ValueError(f"{pt3_path}: not a ProTracker 3 (.pt3) module")
    if shutil.which("sjasmplus") is None:
        raise RuntimeError("sjasmplus not found on PATH (needed to assemble the "
                           "player). See https://github.com/z00m128/sjasmplus.")
    name = (name or os.path.splitext(os.path.basename(pt3_path))[0])[:10]

    with tempfile.TemporaryDirectory() as tmp:
        raw_bin = os.path.join(tmp, "image.bin")
        wrapper = os.path.join(tmp, "wrapper.asm")
        with open(wrapper, "w") as f:
            f.write(_wrapper_asm(PLAYER_ASM, os.path.abspath(pt3_path),
                                 sna=os.path.abspath(sna) if sna else None,
                                 raw_bin=raw_bin))
        proc = subprocess.run(["sjasmplus", "--nologo", wrapper],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("sjasmplus failed:\n" + (proc.stdout + proc.stderr))

        image = open(raw_bin, "rb").read()
        if ORG + len(image) > MEM_TOP:
            raise RuntimeError(
                f"module too large: image is {len(image)} bytes; player + module "
                f"+ stack must fit in {MEM_TOP - ORG} bytes (below ${MEM_TOP:04X}).")

        written = []
        if sna:
            written.append(sna)                      # sjasmplus wrote it directly
        if tap:
            with open(tap, "wb") as f:
                f.write(_build_tap(image, name))
            written.append(tap)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="spectrumizer-pack",
        description="Wrap a .pt3 into a self-playing ZX Spectrum tape / snapshot.")
    p.add_argument("input", help="input .pt3 module")
    p.add_argument("-o", "--output",
                   help="output file; .tap or .sna is chosen by its extension "
                        "(default: input with .tap).")
    p.add_argument("--tap", help="also/instead write a .tap to this path.")
    p.add_argument("--sna", help="also/instead write a .sna (128K snapshot).")
    p.add_argument("--name", help="tape/CODE block name (<=10 chars).")
    p.add_argument("-q", "--quiet", action="store_true")
    args = p.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"spectrumizer-pack: input not found: {args.input}", file=sys.stderr)
        return 2

    tap, sna = args.tap, args.sna
    if args.output:
        if args.output.lower().endswith(".sna"):
            sna = args.output
        else:
            tap = args.output
    if not tap and not sna:
        tap = os.path.splitext(args.input)[0] + ".tap"

    try:
        written = pack(args.input, tap=tap, sna=sna, name=args.name)
    except (RuntimeError, ValueError) as e:
        print(f"spectrumizer-pack: {e}", file=sys.stderr)
        return 1

    if not args.quiet:
        for w in written:
            kind = "snapshot" if w.lower().endswith(".sna") else "tape"
            print(f"spectrumizer-pack: {args.input} -> {w}  ({kind})")
        print("  load the .sna (or the .tap in 128K/128-BASIC mode) so the AY is present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
