#!/usr/bin/env python3
"""Check a rendered screenshot without image libraries: decode the PNG with the standard library, sample pixels
on a grid, and report whether it is blank, made of flat colour blocks, or has real content.

Input (JSON on stdin): path; optional sample_cols, sample_rows (sampling grid, default 8 x 6); optional
block_cols, block_rows, block_threshold (split the image into blocks and report which are a single flat colour).
"""
import json
import struct
import sys
import zlib

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}       # PNG colour type -> samples per pixel


def die(msg):
    sys.stderr.write(str(msg) + "\n")
    raise SystemExit(1)


def chunks(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        die("not a PNG file")
    off, out, idat = 8, {}, []
    while off + 12 <= len(data):
        length, typ = struct.unpack(">I4s", data[off:off + 8])
        if off + 12 + length > len(data):
            die("PNG chunk truncation")
        body = data[off + 8:off + 8 + length]
        if typ == b"IDAT":
            idat.append(body)
        elif typ in (b"IHDR", b"PLTE"):
            out[typ] = body
        elif typ == b"IEND":
            break
        off += 12 + length
    if b"IHDR" not in out or not idat:
        die("missing IHDR or IDAT")
    return out, b"".join(idat)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def unfilter(raw, height, stride, bpp):
    """Undo PNG's per-row filters. The left / upper-left neighbours are one PIXEL (bpp bytes) back."""
    rows, prev = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if kind == 1:
                line[x] = (line[x] + a) & 0xFF
            elif kind == 2:
                line[x] = (line[x] + b) & 0xFF
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif kind == 4:
                line[x] = (line[x] + paeth(a, b, c)) & 0xFF
            elif kind != 0:
                die("unknown PNG filter %d" % kind)
        rows.append(line)
        prev = line
    return rows


def decode(data):
    found, idat = chunks(data)
    width, height, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", found[b"IHDR"])
    if width == 0 or height == 0:
        die("zero-size PNG")
    if comp != 0 or filt != 0 or interlace != 0:
        die("unsupported PNG (compression, filter method or interlacing)")
    if ctype not in CHANNELS or depth not in ((8,) if ctype == 3 else (8, 16)):
        die("unsupported PNG: colour type %d at %d bits" % (ctype, depth))
    if ctype == 3 and b"PLTE" not in found:
        die("palette PNG without PLTE")
    try:
        raw = zlib.decompress(idat)
    except zlib.error as e:
        die("IDAT inflate failed: %s" % e)
    size = depth // 8
    bpp = CHANNELS[ctype] * size
    stride = width * bpp
    if len(raw) < (stride + 1) * height:
        die("PNG image data is too short")
    rows = unfilter(raw, height, stride, bpp)
    pal = found.get(b"PLTE", b"")

    def pixel(x, y):
        row, i = rows[y], x * bpp
        s = [row[i + k * size] for k in range(CHANNELS[ctype])]   # the high byte of each sample
        if ctype == 3:
            j = s[0] * 3
            if j + 3 > len(pal):
                die("palette index out of range")
            return tuple(pal[j:j + 3])
        if ctype in (0, 4):
            return (s[0], s[0], s[0])
        return (s[0], s[1], s[2])

    return width, height, depth, ctype, pixel


def blank_like(r, g, b):
    """Near black, near white, or light grey: what an empty page or an unrendered canvas looks like."""
    luma = int(0.299 * r + 0.587 * g + 0.114 * b + 0.5)
    return luma < 40 or luma > 215 or (max(r, g, b) - min(r, g, b) < 20 and luma >= 140)


def flat_blocks(pixel, width, height, cols, rows, threshold):
    grid = []
    for by in range(rows):
        y0, y1 = by * height // rows, max(by * height // rows + 1, (by + 1) * height // rows)
        line = []
        for bx in range(cols):
            x0, x1 = bx * width // cols, max(bx * width // cols + 1, (bx + 1) * width // cols)
            vals = [pixel(x, y) for y in range(y0, y1, max(1, (y1 - y0) // 8))
                    for x in range(x0, x1, max(1, (x1 - x0) // 8))]
            r0, g0, b0 = vals[0]
            dev = max(max(abs(r - r0), abs(g - g0), abs(b - b0)) for r, g, b in vals)
            line.append(dev <= threshold)
        grid.append(line)
    return grid


def main():
    try:
        args = json.load(sys.stdin)
    except ValueError as e:
        die("invalid JSON input: %s" % e)
    path = args.get("path")
    if not isinstance(path, str) or not path:
        die("path is required")
    cols, rows = int(args.get("sample_cols", 8)), int(args.get("sample_rows", 6))
    if not (1 <= cols <= 512 and 1 <= rows <= 512):
        die("sample grid out of range")
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        die("could not read %s: %s" % (path, e))
    width, height, depth, ctype, pixel = decode(data)

    samples = [pixel(int((i + 0.5) * width / cols), int((j + 0.5) * height / rows))
               for j in range(rows) for i in range(cols)]
    blank_ratio = sum(1 for p in samples if blank_like(*p)) / float(len(samples))
    first = samples[0]
    uniform = all(max(abs(p[k] - first[k]) for k in range(3)) < 5 for p in samples)
    blank = blank_ratio >= 0.95 or uniform
    mean = [sum(p[k] for p in samples) // len(samples) for k in range(3)]

    out = {"path": path, "width": width, "height": height, "color_type": ctype, "bit_depth": depth,
           "sample_cols": cols, "sample_rows": rows, "blank": blank, "blank_ratio": round(blank_ratio, 4),
           "mean_rgb": mean, "mean_luma": int(0.299 * mean[0] + 0.587 * mean[1] + 0.114 * mean[2] + 0.5)}
    flat_share = 0.0
    bc, br = args.get("block_cols"), args.get("block_rows")
    if bc and br:
        if int(bc) < 2 or int(br) < 2:
            die("block grid too small")
        grid = flat_blocks(pixel, width, height, int(bc), int(br), float(args.get("block_threshold", 32.0)))
        flat_share = sum(map(sum, grid)) / float(int(bc) * int(br))
        out.update(block_cols=int(bc), block_rows=int(br), uniform_blocks=round(flat_share, 4), block_uniformity=grid)
    # blank: nothing rendered; flat: almost every block is one solid colour (e.g. textures missing); else content
    out["verdict"] = "blank" if blank else ("flat" if flat_share >= 0.9 else "content")
    sys.stdout.write(json.dumps(out, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
