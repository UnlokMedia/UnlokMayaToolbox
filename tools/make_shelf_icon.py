"""Draw the toolbox's AM_Custom shelf icon (Pillow; not part of the paste).

    python tools/make_shelf_icon.py [out_dir]

Writes TAB_UnlokToolbox_icon_128px.png (403 x 128, the size and layout of
the other AM_Custom shelf "tab" icons: a pill with a dark outline, a
coloured block on the left with a white symbol, the name in white Poppins
Bold on dark grey) and a 32 x 32 square variant, into out_dir (default
shelf/ in this repo). The left block is the toolbox's own teal (ACCENT).
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "shelf")
S = 4  # supersampling
OUTLINE = (45, 45, 45, 255)
DARK = (55, 55, 55, 255)
TEAL = (47, 143, 131, 255)
TEAL_DARK = (31, 102, 93, 255)
WHITE = (255, 255, 255, 255)
FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "Poppins-Bold.ttf")


def toolbox_glyph(d, cx, cy, size):
    """A white toolbox: lid band, body, handle, latch; size = body width."""
    w = size
    h = size * 0.62
    x0, y0 = cx - w / 2, cy - h / 2 + size * 0.10
    r = size * 0.09
    # handle
    hw, hh, t = w * 0.42, size * 0.22, size * 0.085
    d.rounded_rectangle((cx - hw / 2, y0 - hh, cx + hw / 2, y0 + t), radius=hh * 0.45, fill=WHITE)
    d.rounded_rectangle((cx - hw / 2 + t, y0 - hh + t, cx + hw / 2 - t, y0 + t), radius=hh * 0.3, fill=TEAL)
    # body
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=r, fill=WHITE)
    # lid seam
    seam = y0 + h * 0.36
    d.rectangle((x0, seam - size * 0.022, x0 + w, seam + size * 0.022), fill=TEAL_DARK)
    # latch
    lw, lh = w * 0.16, h * 0.30
    d.rounded_rectangle((cx - lw / 2, seam - lh * 0.45, cx + lw / 2, seam + lh * 0.55), radius=lw * 0.2,
                        fill=TEAL_DARK)
    d.rounded_rectangle((cx - lw / 2 + size * 0.03, seam - lh * 0.45 + size * 0.03, cx + lw / 2 - size * 0.03,
                         seam + lh * 0.55 - size * 0.03), radius=lw * 0.1, fill=WHITE)


def tab_icon(lines=("Unlok", "Toolbox")):
    W, H = 403, 128
    im = Image.new("RGBA", (W * S, H * S), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = 7 * S, 2 * S, 396 * S, 125 * S
    rad = (y1 - y0) // 2
    d.rounded_rectangle((x0, y0, x1, y1), radius=rad, fill=OUTLINE)
    b = 4 * S
    inner = (x0 + b, y0 + b, x1 - b, y1 - b)
    d.rounded_rectangle(inner, radius=rad - b, fill=DARK)
    # left block: the inner pill clipped at x = 138
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(inner, radius=rad - b, fill=255)
    ImageDraw.Draw(mask).rectangle((138 * S, 0, W * S, H * S), fill=0)
    im.paste(Image.new("RGBA", im.size, TEAL), (0, 0), mask)
    toolbox_glyph(d, 76 * S, 64 * S, 78 * S)
    font = ImageFont.truetype(FONT, 37 * S)
    ys = (60, 99) if len(lines) == 2 else (80,)
    for text, base in zip(lines, ys):
        d.text((170 * S, base * S), text, font=font, fill=WHITE, anchor="ls")
    return im.resize((W, H), Image.LANCZOS)


def square_icon(n=32):
    im = Image.new("RGBA", (n * S * 4, n * S * 4), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    m = im.size[0]
    d.rounded_rectangle((0, 0, m - 1, m - 1), radius=m * 0.2, fill=TEAL)
    toolbox_glyph(d, m / 2, m / 2, m * 0.70)
    return im.resize((n, n), Image.LANCZOS)


def main(argv):
    out = argv[0] if argv else OUT
    if not os.path.isdir(out):
        os.makedirs(out)
    tab_icon().save(os.path.join(out, "TAB_UnlokToolbox_icon_128px.png"))
    square_icon(32).save(os.path.join(out, "UnlokToolbox_32.png"))
    square_icon(64).save(os.path.join(out, "UnlokToolbox_64.png"))
    print("wrote icons to", out)


if __name__ == "__main__":
    main(sys.argv[1:])
