"""Generate PWA icon set from the CampusOS brand gradient.

Produces:
  static/icons/icon-192.png             — Android home screen (manifest)
  static/icons/icon-512.png             — Android splash + large surfaces
  static/icons/icon-512-maskable.png    — Android adaptive icon (safe-zone padded)
  static/icons/apple-touch-icon.png     — iOS 180x180 home screen
  static/icons/favicon-32.png           — browser tab favicon

Run once after a brand change:
    python generate_icons.py
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT_DIR = os.path.join("static", "icons")
os.makedirs(OUT_DIR, exist_ok=True)

# Brand stops: indigo → violet → pink (matches --gradient in style.css)
GRADIENT_STOPS = [
    (0.00, (99, 102, 241)),    # #6366f1 indigo-500
    (0.50, (139, 92, 246)),    # #8b5cf6 violet-500
    (1.00, (236, 72, 153)),    # #ec4899 pink-500
]
WORDMARK = "CO"
WORDMARK_COLOR = (255, 255, 255)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def color_at(t):
    """Sample the multi-stop gradient at position t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    for i in range(len(GRADIENT_STOPS) - 1):
        t0, c0 = GRADIENT_STOPS[i]
        t1, c1 = GRADIENT_STOPS[i + 1]
        if t0 <= t <= t1:
            local_t = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return lerp(c0, c1, local_t)
    return GRADIENT_STOPS[-1][1]


def make_gradient_canvas(size):
    """Return a square RGB image with a 135deg diagonal gradient."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    # 135deg means top-left → bottom-right; for each pixel use (x+y)/(2w-1)
    denom = 2 * (size - 1)
    for y in range(size):
        for x in range(size):
            t = (x + y) / denom
            px[x, y] = color_at(t)
    return img


def best_font(size_px):
    """Locate a chunky sans for the wordmark. Tries Outfit/Arial Black/system bold."""
    candidates = [
        "C:/Windows/Fonts/ariblk.ttf",   # Arial Black on Windows
        "C:/Windows/Fonts/arialbd.ttf",  # Arial Bold
        "C:/Windows/Fonts/segoeuib.ttf", # Segoe UI Bold
        "/Library/Fonts/Arial Black.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVu-Sans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size_px)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_wordmark(img, scale=0.55):
    """Center the WORDMARK over the gradient at a given fraction of the canvas."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    font_size = int(min(w, h) * scale)
    font = best_font(font_size)

    # Measure with textbbox so the centering is correct across PIL versions
    bbox = draw.textbbox((0, 0), WORDMARK, font=font, anchor="lt")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (w - text_w) / 2 - bbox[0]
    # Optical centering: ascenders pull text visually upward, so nudge down ~6%
    y = (h - text_h) / 2 - bbox[1] + int(h * 0.02)
    draw.text((x, y), WORDMARK, fill=WORDMARK_COLOR, font=font)
    return img


def make_icon(size, maskable=False):
    """Build a square icon. Maskable variant shrinks the wordmark into the
    central 80% safe zone so Android's adaptive cropping doesn't clip it."""
    img = make_gradient_canvas(size)
    if maskable:
        # Safe zone: keep the wordmark within ~64% of the canvas so the
        # 80% safe-zone crop still has comfortable margin on all sides.
        draw_wordmark(img, scale=0.42)
    else:
        draw_wordmark(img, scale=0.55)
    return img


def main():
    targets = [
        ("icon-192.png",          192, False),
        ("icon-512.png",          512, False),
        ("icon-512-maskable.png", 512, True),
        ("apple-touch-icon.png",  180, False),
        ("favicon-32.png",         32, False),
    ]
    for name, size, maskable in targets:
        path = os.path.join(OUT_DIR, name)
        icon = make_icon(size, maskable=maskable)
        icon.save(path, "PNG", optimize=True)
        print(f"  wrote {path}  ({size}x{size}{', maskable' if maskable else ''})")


if __name__ == "__main__":
    main()
