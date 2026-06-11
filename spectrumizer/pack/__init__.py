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
    """The sjasmplus source: title screen + IM1 loader + Bulba player + module.

    The title screen prints with the ROM font (we page in ROM 1, the 48K
    BASIC ROM, so it sits at $3D00 on 128K machines too; the OUT is a no-op
    on a real 48K). Song title and author are read straight from the .pt3
    header (offsets $1E and $42), so any module shows its own credits."""
    save_sna = f'    SAVESNA "{sna}", main\n' if sna else ""
    return f"""\
    DEVICE ZXSPECTRUM128
    ORG ${ORG:04X}
main:
    di
    ld sp, stacktop
    ld bc, $7ffd            ; page ROM 1 (48K ROM: the font), bank 0, screen 5
    ld a, $10               ; harmless on a 48K machine (port unmapped)
    out (c), a
    call screen             ; draw the title screen
    ld hl, module
    call START+3            ; init player with module address in HL
    ei
.loop:
    halt                    ; wait for the 50 Hz interrupt (IM1, ROM handler)
    call START+5            ; play one frame
    call anim               ; rainbow-cycle the logo attributes
    jr .loop

; ------------------------------------------------------------- title screen
screen:
    xor a
    out ($fe), a            ; black border
    ld hl, $4000            ; clear pixels + attrs to 0 (ink 0 on paper 0):
    ld de, $4001            ; text only shows once its row attr is set below
    ld bc, $1aff
    ld (hl), a
    ldir
    ld b, 1
    ld c, 10
    ld hl, logo_txt
    call prtext
    ld b, 3
    ld c, 5
    ld hl, sub_txt
    call prtext
    ld hl, module+$1e       ; song title, straight from the PT3 header
    ld d, 32
    ld b, 11
    call center
    ld hl, module+$42       ; author field: skip the row when blank
    ld b, 32
.chk:
    ld a, (hl)
    cp 32
    jr nz, .author
    inc hl
    djnz .chk
    jr .credits
.author:
    ld hl, by_txt           ; compose "by <author>" and centre it
    ld de, buf
    ld bc, 3
    ldir
    ld hl, module+$42
    ld bc, 32
    ldir
    ld hl, buf
    ld d, 35
    ld b, 13
    call center
.credits:
    ld b, 22
    ld c, 5
    ld hl, url_txt
    call prtext
    ld b, 1                 ; reveal each text row with its colour
    ld e, $47               ; (paper stays black everywhere)
    call filla
    ld b, 3
    ld e, $07
    call filla
    ld b, 11
    ld e, $47
    call filla
    ld b, 13
    ld e, $07
    call filla
    ld b, 22
    ld e, $06
    call filla
    ret

center:                     ; centre HL (field of D bytes, row B), spaces cut
    push hl
    ld e, d
    ld d, 0
    add hl, de
.scan:
    dec hl
    ld a, (hl)
    cp 32
    jr nz, .found
    dec e
    jr nz, .scan
    pop hl
    ret                     ; all spaces: nothing to print
.found:
    pop hl
    ld a, e
    cp 33
    jr c, .fits
    ld e, 32                ; clamp to one screen row
.fits:
    ld a, 32
    sub e
    srl a
    ld c, a                 ; col = (32 - len) / 2
    ld a, e                 ; fall through with A = count
prtextn:                    ; print A chars from HL at row B, col C
    push af
    ld a, (hl)
    inc hl
    call prchar
    inc c
    pop af
    dec a
    jr nz, prtextn
    ret

prtext:                     ; print asciiz HL at row B, col C
    ld a, (hl)
    or a
    ret z
    inc hl
    call prchar
    inc c
    jr prtext

prchar:                     ; glyph A at (row B, col C); preserves BC, HL
    push bc
    push hl
    cp 32
    jr c, .blank
    cp 128
    jr c, .ok
.blank:
    ld a, 32                ; outside the ROM font: print a space
.ok:
    ld l, a
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    ld de, $3c00            ; ROM font: glyph = $3C00 + char*8
    add hl, de
    ld a, b                 ; screen addr: $40|(row&$18) : (row&7)<<5 | col
    and $18
    or $40
    ld d, a
    ld a, b
    and 7
    rrca
    rrca
    rrca
    or c
    ld e, a
    ld b, 8
.row:
    ld a, (hl)
    ld (de), a
    inc hl
    inc d
    djnz .row
    pop hl
    pop bc
    ret

filla:                      ; fill row B's 32 attribute cells with E
    ld l, b
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl              ; HL = row*32; add $5800 via H so E survives
    ld a, h
    add a, $58
    ld h, a
    ld b, 32
.fa:
    ld (hl), e
    inc hl
    djnz .fa
    ret

anim:                       ; rainbow-wave the logo attrs every 4 frames
    ld hl, frame
    inc (hl)
    ld a, (hl)
    and 3
    ret nz
    inc hl
    inc (hl)                ; phase advances the wave one step
    ld a, (hl)
    ld de, $5800+32+10      ; row 1, cols 10..21: "spectrumizer"
    ld b, 12
    ld c, a
.an:
    ld a, c
    and 15
    ld hl, rainbow
    add a, l
    ld l, a
    jr nc, .nc
    inc h
.nc:
    ld a, (hl)
    ld (de), a
    inc de
    inc c
    djnz .an
    ret

logo_txt:
    db "spectrumizer", 0
sub_txt:
    db "MIDI -> ZX Spectrum AY", 0
by_txt:
    db "by "
url_txt:
    db "github.com/revengator", 0
rainbow:                    ; bright ink on black, one wave period
    db $42,$42,$46,$46,$44,$44,$45,$45,$47,$47,$45,$45,$44,$44,$46,$46
frame:
    db 0
phase:
    db 0
buf:
    ds 35

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
    from .. import __version__
    p = argparse.ArgumentParser(
        prog="spectrumizer-pack",
        description="Wrap a .pt3 into a self-playing ZX Spectrum tape / snapshot.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
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
