#!/usr/bin/env python3
import sys, json, zlib, struct

def die(msg):
    sys.stderr.write(str(msg) + "\n")
    sys.exit(1)

def read_png(path):
    with open(path, "rb") as f:
        return f.read()

def read_chunks(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        die("not a PNG file")
    off = 8
    chunks = {}
    idat = []
    while off + 12 <= len(data):
        (length,) = struct.unpack(">I", data[off:off+4])
        typ = data[off+4:off+8]
        chunk = data[off+8:off+8+length]
        crc = data[off+8+length:off+12+length]
        if length < 0 or off + 12 + length > len(data):
            die("PNG chunk truncation")
        if typ == b"IHDR":
            chunks[typ.decode("ascii")] = chunk
        elif typ == b"PLTE":
            chunks[typ.decode("ascii")] = chunk
        elif typ == b"IDAT":
            idat.append(chunk)
        off += 12 + length
    if not idat:
        die("no IDAT")
    return chunks, idat

def decode_png(data, path):
    chunks, idat = read_chunks(data)
    ihdr = chunks.get("IHDR")
    if not ihdr:
        die("missing IHDR")
    width = struct.unpack(">I", ihdr[0:4])[0]
    height = struct.unpack(">I", ihdr[4:8])[0]
    if width == 0 or height == 0:
        die("zero-size PNG")
    bit_depth = ihdr[8]
    color_type = ihdr[9]
    compression = ihdr[10]
    filter = ihdr[11]
    interlace = ihdr[12]
    if compression != 0 or filter != 0:
        die("unsupported compression/filter")
    if interlace != 0:
        die("interlaced PNG not supported")
    if bit_depth not in (8, 16):
        die("only 8/16-bit PNG is supported")
    if color_type not in (0, 2, 3, 4, 6):
        die("unsupported color type")
    if color_type == 3 and "PLTE" not in chunks:
        die("palette PNG without PLTE")
    try:
        raw = zlib.decompress(b"".join(idat))
    except Exception as e:
        die("IDAT inflate failed: %r" % (e,))

    img = []

    if color_type in (0, 4):
        cpp = 2 if color_type == 4 else 1
        stride = width * cpp
        raw_stride = stride + 1
        if len(raw) != raw_stride * height:
            die("raw PNG size mismatch")
        prev_row = [0] * stride
        for y in range(height):
            filt = raw[y*raw_stride]
            line = raw[y*raw_stride + 1 : (y+1)*raw_stride]
            row = []
            for x in range(stride):
                left = row[x-1] if x > 0 else 0
                up = prev_row[x]
                upleft = prev_row[x-1] if x > 0 else 0
                v = line[x]
                if filt == 1:
                    v = (v + left) & 0xff
                elif filt == 2:
                    v = (v + up) & 0xff
                elif filt == 3:
                    v = (v + (left + up)//2) & 0xff
                elif filt == 4:
                    a = left + up - upleft
                    if 0 <= a <= 255: paeth = a
                    elif a < 0: paeth = -a
                    else: paeth = a
                    if paeth == left: p = left
                    elif paeth == up: p = up
                    else: p = upleft
                    v = (v + p) & 0xff
                row.append(v)
            prev_row = row[:]
            for x in range(width):
                v = row[x*cpp]
                if bit_depth == 16:
                    v1 = (row[x*cpp] << 8) | row[x*cpp+1]
                    v = int(v1 / 257.0)
                img.append((v, v, v))
        return img

    if color_type == 3:
        pal = chunks["PLTE"]
        stride = width
        raw_stride = stride + 1
        if len(raw) != raw_stride * height:
            die("raw PNG size mismatch")
        prev_row = [0] * stride
        for y in range(height):
            filt = raw[y*raw_stride]
            line = raw[y*raw_stride + 1 : (y+1)*raw_stride]
            row = []
            for x in range(stride):
                left = row[x-1] if x > 0 else 0
                up = prev_row[x]
                upleft = prev_row[x-1] if x > 0 else 0
                v = line[x]
                if filt == 1:
                    v = (v + left) & 0xff
                elif filt == 2:
                    v = (v + up) & 0xff
                elif filt == 3:
                    v = (v + (left + up)//2) & 0xff
                elif filt == 4:
                    a = left + up - upleft
                    if 0 <= a <= 255: paeth = a
                    elif a < 0: paeth = -a
                    else: paeth = a
                    if paeth == left: p = left
                    elif paeth == up: p = up
                    else: p = upleft
                    v = (v + p) & 0xff
                row.append(v)
            prev_row = row[:]
            for x in range(width):
                idx = row[x]
                off = idx*3
                if off+2 >= len(pal):
                    die("palette index out of range")
                img.append(tuple(pal[off:off+3]))
        return img

    cpp = 3 if color_type == 2 else 4
    stride = width * cpp
    raw_stride = stride + 1
    if len(raw) != raw_stride * height:
        die("raw PNG size mismatch")
    prev_row = [0] * stride
    for y in range(height):
        filt = raw[y*raw_stride]
        line = raw[y*raw_stride + 1 : (y+1)*raw_stride]
        row = []
        for x in range(stride):
            left = row[x-1] if x > 0 else 0
            up = prev_row[x]
            upleft = prev_row[x-1] if x > 0 else 0
            v = line[x]
            if filt == 1:
                v = (v + left) & 0xff
            elif filt == 2:
                v = (v + up) & 0xff
            elif filt == 3:
                v = (v + (left + up)//2) & 0xff
            elif filt == 4:
                a = left + up - upleft
                if 0 <= a <= 255: paeth = a
                elif a < 0: paeth = -a
                else: paeth = a
                if paeth == left: p = left
                elif paeth == up: p = up
                else: p = upleft
                v = (v + p) & 0xff
            row.append(v)
        prev_row = row[:]
        for x in range(width):
            base = x*cpp
            r = row[base]
            g = row[base+1]
            b = row[base+2]
            if bit_depth == 16:
                r = int(((row[base] << 8) | row[base+1]) / 257.0)
                g = int(((row[base+2] << 8) | row[base+3]) / 257.0)
                b = int(((row[base+4] << 8) | row[base+5]) / 257.0)
            img.append((r, g, b))
    return img

def pixel(img, width, x, y):
    idx = y * width + x
    if idx < 0 or idx >= len(img):
        die("pixel index out of range")
    return img[idx]

def classify(r,g,b):
    mn = min(r,g,b)
    mx = max(r,g,b)
    sat = mx - mn
    luma = int((0.299*r + 0.587*g + 0.114*b + 0.5))
    if luma < 40 or luma > 215:
        return "."
    if sat < 20 and 140 <= luma <= 215:
        return "."
    if b > 150 and b > g > r:
        return "S"
    if g > 90 and g > r > b:
        return "G"
    if r > 110 and r >= g > b:
        return "D"
    if luma > 80:
        return "?"
    return "."

def block_stats(img, width, height, bc, br, thresh):
    rows = []
    for by in range(br):
        y0 = int(by*height/br)
        y1 = int((by+1)*height/br)
        if y1 <= y0: y1 = y0 + 1
        if y1 > height: y1 = height
        cols = []
        for bx in range(bc):
            x0 = int(bx*width/bc)
            x1 = int((bx+1)*width/bc)
            if x1 <= x0: x1 = x0 + 1
            if x1 > width: x1 = width
            vals = []
            ys = list(range(y0, min(y1, height), max(1, (y1-y0)//8)))
            xs = list(range(x0, min(x1, width), max(1, (x1-x0)//8)))
            for yy in ys:
                for xx in xs:
                    vals.append(pixel(img, width, xx, yy))
            if not vals:
                die("empty block sample")
            r0,g0,b0 = vals[0]
            dev = max(
                max(abs(r - r0) for (r,g,b) in vals),
                max(abs(g - g0) for (r,g,b) in vals),
                max(abs(b - b0) for (r,g,b) in vals),
            )
            cols.append(dev <= thresh)
        rows.append(cols)
    return rows

def main():
    try:
        args = json.load(sys.stdin)
    except Exception as e:
        die("invalid JSON input: %r" % (e,))
    path = args.get("path")
    if not path or not isinstance(path, str):
        die("path is required")
    sample_cols = int(args.get("sample_cols", 8))
    sample_rows = int(args.get("sample_rows", 6))
    block_cols = args.get("block_cols")
    block_rows = args.get("block_rows")
    block_threshold = float(args.get("block_threshold", 32.0))
    if sample_cols < 1 or sample_rows < 1 or sample_cols > 512 or sample_rows > 512:
        die("sample grid out of range")
    try:
        data = read_png(path)
        img = decode_png(data, path)
    except Exception as e:
        die("could not decode PNG: %r" % (e,))
    chunks, idat = read_chunks(data)
    ihdr = chunks["IHDR"]
    width = struct.unpack(">I", ihdr[0:4])[0]
    height = struct.unpack(">I", ihdr[4:8])[0]
    bit_depth = ihdr[8]
    color_type = ihdr[9]

    samples = []
    for j in range(sample_rows):
        y = int((j + 0.5) * height / sample_rows)
        for i in range(sample_cols):
            x = int((i + 0.5) * width / sample_cols)
            samples.append(pixel(img, width, x, y))
    if not samples:
        die("no samples")

    blank_count = 0
    grid_rows = []
    for j in range(sample_rows):
        row = []
        for i in range(sample_cols):
            idx = j * sample_cols + i
            r,g,b = samples[idx]
            cls = classify(r,g,b)
            if cls == ".":
                blank_count += 1
            row.append(cls)
        grid_rows.append("".join(row))

    blank_ratio = blank_count / float(len(samples))
    blank = (blank_ratio >= 0.95) or (
        max(samples, key=lambda p:p[0]) is min(samples, key=lambda p:p[0])
        and all(abs(p[0]-samples[0][0])<5 and abs(p[1]-samples[0][1])<5 and abs(p[2]-samples[0][2])<5 for p in samples)
    )

    mean_rgb = tuple(sum(c[k] for c in samples)//len(samples) for k in range(3))
    mean_luma = int((0.299*mean_rgb[0] + 0.587*mean_rgb[1] + 0.114*mean_rgb[2] + 0.5))

    block_rows_out = None
    uniform_count = 0
    block_total = 0
    if block_cols and block_rows:
        if block_cols < 2 or block_rows < 2:
            die("block grid too small")
        block_rows_out = block_stats(img, width, height, int(block_cols), int(block_rows), block_threshold)
        for br in block_rows_out:
            for uniform in br:
                block_total += 1
                if uniform:
                    uniform_count += 1

    uniform_blocks = (uniform_count / float(block_total)) if block_total else 0.0

    if blank:
        verdict = "blank"
    elif block_total and uniform_blocks >= 0.90:
        verdict = "incorrect"
    elif len(samples) < width * height * 0.01:
        verdict = "sparse"
    else:
        verdict = "content"

    out = {
        "path": path,
        "width": width,
        "height": height,
        "color_type": color_type,
        "bit_depth": bit_depth,
        "sample_cols": sample_cols,
        "sample_rows": sample_rows,
        "blank": bool(blank),
        "blank_ratio": round(blank_ratio, 4),
        "mean_rgb": list(mean_rgb),
        "mean_luma": mean_luma,
        "verdict": verdict,
    }
    if block_rows_out is not None:
        out["block_cols"] = int(block_cols)
        out["block_rows"] = int(block_rows)
        out["uniform_blocks"] = round(uniform_blocks, 4)
        out["block_uniformity"] = block_rows_out

    sys.stdout.write(json.dumps(out, separators=(",",":")) + "\n")

if __name__ == "__main__":
    main()
