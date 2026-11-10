"""Generate the original demo creatures used in examples/demo_images.

These are simple procedurally drawn critters, so the repository ships without
any third-party artwork. Run:  python examples/make_demo_images.py
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "demo_images"
SS = 4  # supersampling

PALETTES = {
    "violet": [(92, 52, 120), (150, 96, 170), (235, 222, 205), (205, 60, 80)],
    "teal": [(30, 90, 95), (60, 150, 150), (230, 225, 200), (240, 170, 60)],
    "rust": [(110, 45, 35), (175, 85, 55), (238, 226, 205), (90, 160, 90)],
}


def critter(height, width_ratio=1.0, legs=6, spikes=5, palette="violet", seed=0, wings=False, tall=False):
    rnd = random.Random(seed)
    dark, mid, bone, accent = PALETTES[palette]
    H = height * SS
    W = int(H * (1.4 if not tall else 0.9) * width_ratio)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = W / 2
    ground = H * 0.97
    body_h = H * (0.38 if not tall else 0.30)
    body_w = W * (0.55 if not tall else 0.45)
    body_y = ground - H * (0.45 if not tall else 0.55)

    # base
    d.ellipse([cx - W * 0.42, ground - H * 0.05, cx + W * 0.42, ground + H * 0.03], fill=(85, 95, 60, 255))
    # wings
    if wings:
        for s in (-1, 1):
            d.polygon([(cx, body_y), (cx + s * W * 0.5, body_y - H * 0.45), (cx + s * W * 0.42, body_y + H * 0.05)],
                      fill=mid + (235,), outline=dark)
    # legs
    for i in range(legs):
        s = -1 if i % 2 else 1
        k = i // 2
        x0 = cx + s * body_w * (0.15 + 0.12 * k)
        knee = (x0 + s * W * (0.12 + 0.05 * k), body_y - H * 0.02 + rnd.uniform(-H * 0.05, H * 0.03))
        foot = (x0 + s * W * (0.18 + 0.06 * k), ground - H * 0.02)
        lw = int(H * 0.035)
        d.line([(x0, body_y), knee, foot], fill=bone, width=lw, joint="curve")
        d.line([knee, foot], fill=dark, width=max(1, lw // 3))
    # body
    d.ellipse([cx - body_w / 2, body_y - body_h / 2, cx + body_w / 2, body_y + body_h / 2], fill=bone, outline=dark,
              width=int(H * 0.01))
    # carapace plates
    for i in range(4):
        t = i / 4
        d.chord([cx - body_w / 2 + t * body_w * 0.2, body_y - body_h / 2 - H * 0.02,
                 cx + body_w / 2 - t * body_w * 0.2, body_y + body_h * (0.1 - 0.12 * i)],
                180, 360, fill=mid if i % 2 else dark)
    # spikes
    for i in range(spikes):
        a = math.pi * (0.15 + 0.7 * i / max(1, spikes - 1))
        bx = cx - math.cos(a) * body_w * 0.45
        by = body_y - math.sin(a) * body_h * 0.45
        tx = cx - math.cos(a) * body_w * 0.8
        ty = body_y - math.sin(a) * body_h * 1.2 - H * 0.05
        d.polygon([(bx - H * 0.02, by), (bx + H * 0.02, by), (tx, ty)], fill=dark)
    # head
    hx = cx + body_w * 0.45
    hy = body_y - body_h * (0.05 if not tall else 0.6)
    hr = H * (0.11 if not tall else 0.09)
    d.ellipse([hx - hr, hy - hr * 0.8, hx + hr * 1.3, hy + hr * 0.8], fill=bone, outline=dark, width=int(H * 0.008))
    d.chord([hx - hr, hy - hr, hx + hr * 1.3, hy + hr * 0.2], 180, 360, fill=dark)
    d.ellipse([hx + hr * 0.5, hy - hr * 0.25, hx + hr * 0.8, hy + hr * 0.05], fill=accent)
    d.line([(hx + hr * 0.2, hy + hr * 0.45), (hx + hr * 1.2, hy + hr * 0.35)], fill=accent, width=int(H * 0.012))
    # tail
    d.line([(cx - body_w * 0.45, body_y + body_h * 0.1), (cx - W * 0.43, body_y + H * 0.15),
            (cx - W * 0.47, body_y - H * 0.05)], fill=bone, width=int(H * 0.03), joint="curve")

    im = im.filter(ImageFilter.SMOOTH)
    return im.resize((W // SS, H // SS), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    specs = {
        "little-monster-a": dict(height=90, legs=6, spikes=3, palette="violet", seed=1),
        "little-monster-b": dict(height=88, legs=6, spikes=4, palette="violet", seed=2),
        "spitting-monster": dict(height=100, legs=4, spikes=4, palette="teal", seed=3),
        "boss-monster": dict(height=210, legs=4, spikes=6, palette="rust", seed=4, tall=True),
        "spiky-monster": dict(height=330, legs=6, spikes=7, palette="violet", seed=5),
        "flying-monster": dict(height=260, legs=2, spikes=5, palette="teal", seed=6, wings=True, tall=True),
        "big-monster": dict(height=520, legs=6, spikes=9, palette="rust", seed=7, width_ratio=1.1),
        "smart-monster": dict(height=300, legs=4, spikes=6, palette="teal", seed=8, tall=True),
    }
    for name, spec in specs.items():
        critter(**spec).save(OUT / f"{name}.png")
        print("wrote", name)
    demo_dispositions()


def demo_dispositions():
    """Simple placeholder icons, one per disposition."""
    out = OUT / "dispositions"
    out.mkdir(exist_ok=True)
    colors = [(60, 140, 80), (50, 100, 160), (170, 50, 60), (190, 150, 40), (40, 140, 140)]
    names = ["take-and-hold", "disruption", "purge-the-foe", "priority-assets", "reconnaissance"]
    S = 120 * SS
    for i, (name, col) in enumerate(zip(names, colors)):
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([S * 0.08, S * 0.08, S * 0.92, S * 0.92], S * 0.22, fill=col,
                            outline=(30, 30, 30), width=S // 40)
        w = (245, 240, 230)
        c = S / 2
        if i == 0:   # flag
            d.line([(c - S * 0.15, S * 0.25), (c - S * 0.15, S * 0.78)], fill=w, width=S // 18)
            d.polygon([(c - S * 0.15, S * 0.25), (c + S * 0.25, S * 0.35), (c - S * 0.15, S * 0.47)], fill=w)
        elif i == 1:  # lightning
            d.polygon([(c + S * 0.05, S * 0.2), (c - S * 0.18, S * 0.52), (c, S * 0.52), (c - S * 0.05, S * 0.8),
                       (c + S * 0.18, S * 0.45), (c, S * 0.45)], fill=w)
        elif i == 2:  # crosshair
            d.ellipse([c - S * 0.22, c - S * 0.22, c + S * 0.22, c + S * 0.22], outline=w, width=S // 22)
            d.line([(c, S * 0.2), (c, S * 0.8)], fill=w, width=S // 26)
            d.line([(S * 0.2, c), (S * 0.8, c)], fill=w, width=S // 26)
        elif i == 3:  # star
            pts = []
            for k in range(10):
                r = S * (0.28 if k % 2 == 0 else 0.12)
                a = -math.pi / 2 + k * math.pi / 5
                pts.append((c + r * math.cos(a), c + r * math.sin(a)))
            d.polygon(pts, fill=w)
        else:  # binoculars
            for s in (-1, 1):
                d.ellipse([c + s * S * 0.13 - S * 0.12, c - S * 0.05, c + s * S * 0.13 + S * 0.12, c + S * 0.19],
                          outline=w, width=S // 22)
            d.rectangle([c - S * 0.05, c - S * 0.12, c + S * 0.05, c + S * 0.05], fill=w)
        im.resize((S // SS, S // SS), Image.LANCZOS).save(out / f"{name}.png")


if __name__ == "__main__":
    main()
