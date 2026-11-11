"""Generate the original demo robots used in examples/robot_images (second demo army).

Simple procedurally drawn machines, so the repository ships without any third-party artwork.
Run:  python examples/make_robot_images.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "robot_images"
SS = 4  # supersampling

STEEL = (70, 95, 130)
STEEL_LIGHT = (120, 150, 185)
DARK = (35, 40, 50)
GLOW = (255, 190, 60)
BASE = (85, 95, 60)


def _base(d, cx, ground, w, h):
    d.ellipse([cx - w / 2, ground - h * 0.06, cx + w / 2, ground + h * 0.02], fill=BASE + (255,))


def bot(height, variant=0, gun=True, shield=False, cape=False):
    """A small walking robot: round head with one visor, box body, tube arms and legs."""
    H = height * SS
    W = int(H * 0.8)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, ground = W / 2, H * 0.97
    _base(d, cx, ground, W * 0.8, H)
    lw = H * 0.07
    stride = [(-0.12, 0.10), (-0.05, 0.14), (-0.15, 0.06)][variant % 3]
    hip = ground - H * 0.42
    for s, off in ((-1, stride[0]), (1, stride[1])):
        d.line([(cx + s * W * 0.1, hip), (cx + off * W, ground - H * 0.04)], fill=DARK, width=int(lw))
        d.rounded_rectangle([cx + off * W - W * 0.09, ground - H * 0.07, cx + off * W + W * 0.09, ground - H * 0.02],
                            radius=H * 0.02, fill=STEEL)
    if cape:
        d.polygon([(cx - W * 0.22, hip - H * 0.25), (cx + W * 0.22, hip - H * 0.25),
                   (cx + W * 0.32, ground - H * 0.08), (cx - W * 0.32, ground - H * 0.08)], fill=(150, 40, 40))
    body = [cx - W * 0.22, hip - H * 0.32, cx + W * 0.22, hip + H * 0.03]
    d.rounded_rectangle(body, radius=H * 0.04, fill=STEEL, outline=DARK, width=SS * 2)
    d.rectangle([cx - W * 0.12, hip - H * 0.24, cx + W * 0.12, hip - H * 0.16], fill=STEEL_LIGHT)
    d.ellipse([cx - W * 0.04, hip - H * 0.12, cx + W * 0.04, hip - H * 0.06], fill=GLOW)
    # head: dome with one visor slit, small antenna
    hy = hip - H * 0.42
    d.ellipse([cx - W * 0.15, hy - H * 0.09, cx + W * 0.15, hy + H * 0.11], fill=STEEL_LIGHT, outline=DARK, width=SS * 2)
    d.rounded_rectangle([cx - W * 0.1, hy - H * 0.01, cx + W * 0.12, hy + H * 0.03], radius=H * 0.01, fill=GLOW)
    d.line([(cx + W * 0.05, hy - H * 0.08), (cx + W * 0.09, hy - H * 0.16)], fill=DARK, width=SS * 2)
    d.ellipse([cx + W * 0.07, hy - H * 0.18, cx + W * 0.11, hy - H * 0.14], fill=GLOW)
    sh = hip - H * 0.28
    if shield:
        d.rounded_rectangle([cx - W * 0.42, sh - H * 0.02, cx - W * 0.2, sh + H * 0.3], radius=H * 0.03,
                            fill=STEEL_LIGHT, outline=DARK, width=SS * 2)
        d.line([(cx - W * 0.31, sh + H * 0.03), (cx - W * 0.31, sh + H * 0.25)], fill=GLOW, width=SS * 3)
    else:
        d.line([(cx - W * 0.22, sh), (cx - W * 0.3, sh + H * 0.2)], fill=DARK, width=int(lw * 0.8))
    if gun:
        d.line([(cx + W * 0.22, sh), (cx + W * 0.3, sh + H * 0.14)], fill=DARK, width=int(lw * 0.8))
        d.rectangle([cx + W * 0.24, sh + H * 0.1, cx + W * 0.48, sh + H * 0.16], fill=DARK)
        d.rectangle([cx + W * 0.44, sh + H * 0.115, cx + W * 0.49, sh + H * 0.145], fill=GLOW)
    else:  # glowing blade
        d.line([(cx + W * 0.22, sh), (cx + W * 0.3, sh + H * 0.14)], fill=DARK, width=int(lw * 0.8))
        d.line([(cx + W * 0.3, sh + H * 0.14), (cx + W * 0.45, sh - H * 0.2)], fill=GLOW, width=SS * 5)
    im = im.filter(ImageFilter.SMOOTH)
    return im.resize((W // SS, H // SS), Image.LANCZOS)


def walker(height):
    """A big two-legged walker with a round cockpit and two cannons."""
    H = height * SS
    W = int(H * 1.0)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, ground = W / 2, H * 0.97
    _base(d, cx, ground, W * 0.9, H)
    hip = ground - H * 0.5
    for s in (-1, 1):
        knee = (cx + s * W * 0.28, ground - H * 0.28)
        d.line([(cx + s * W * 0.12, hip), knee, (cx + s * W * 0.2, ground - H * 0.04)], fill=DARK, width=int(H * 0.06),
               joint="curve")
        d.polygon([(cx + s * W * 0.2 - W * 0.12, ground - H * 0.02), (cx + s * W * 0.2 + W * 0.12, ground - H * 0.02),
                   (cx + s * W * 0.2, ground - H * 0.09)], fill=STEEL)
    d.ellipse([cx - W * 0.3, hip - H * 0.38, cx + W * 0.3, hip + H * 0.05], fill=STEEL, outline=DARK, width=SS * 3)
    d.chord([cx - W * 0.18, hip - H * 0.3, cx + W * 0.18, hip - H * 0.12], 180, 360, fill=GLOW)
    for s in (-1, 1):
        y = hip - H * 0.16
        d.rectangle([cx + s * W * 0.28 - (W * 0.18 if s < 0 else 0), y - H * 0.04,
                     cx + s * W * 0.28 + (W * 0.18 if s > 0 else 0), y + H * 0.04], fill=DARK)
        d.rectangle([cx + s * W * 0.46 - W * 0.03, y - H * 0.03, cx + s * W * 0.46 + W * 0.03, y + H * 0.03], fill=GLOW)
    im = im.filter(ImageFilter.SMOOTH)
    return im.resize((W // SS, H // SS), Image.LANCZOS)


def tank(height):
    """A hover tank: flat hull, turret, long gun."""
    H = height * SS
    W = int(H * 2.0)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, ground = W / 2, H * 0.97
    d.ellipse([cx - W * 0.42, ground - H * 0.1, cx + W * 0.42, ground + H * 0.02], fill=(70, 70, 80, 180))
    hull_y = ground - H * 0.25
    d.polygon([(cx - W * 0.45, hull_y), (cx + W * 0.45, hull_y), (cx + W * 0.38, hull_y + H * 0.15),
               (cx - W * 0.38, hull_y + H * 0.15)], fill=STEEL, outline=DARK)
    d.rectangle([cx - W * 0.45, hull_y - H * 0.18, cx + W * 0.45, hull_y], fill=STEEL_LIGHT, outline=DARK, width=SS * 2)
    for k in range(5):
        x = cx - W * 0.35 + k * W * 0.175
        d.ellipse([x - H * 0.03, hull_y + H * 0.04, x + H * 0.03, hull_y + H * 0.1], fill=GLOW)
    ty = hull_y - H * 0.18
    d.chord([cx - W * 0.18, ty - H * 0.28, cx + W * 0.18, ty + H * 0.1], 180, 360, fill=STEEL, outline=DARK, width=SS * 2)
    d.rectangle([cx + W * 0.12, ty - H * 0.16, cx + W * 0.5, ty - H * 0.1], fill=DARK)
    d.rectangle([cx - W * 0.06, ty - H * 0.2, cx + W * 0.06, ty - H * 0.14], fill=GLOW)
    im = im.filter(ImageFilter.SMOOTH)
    return im.resize((W // SS, H // SS), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    images = {
        "tin-soldier-a": bot(110, 0),
        "tin-soldier-b": bot(108, 1),
        "tin-soldier-c": bot(112, 2),
        "shield-bot": bot(120, 1, gun=False, shield=True),
        "robot-captain": bot(135, 0, gun=False, cape=True),
        "walker": walker(330),
        "hover-tank": tank(200),
    }
    for name, img in images.items():
        img.save(OUT / f"{name}.png")
        print("wrote", name)
    (OUT / "bases.json").write_text(
        '{\n  "Tin Soldier": 32,\n  "Shield Bot": 40,\n  "Robot Captain": 40,\n'
        '  "Walker": 90,\n  "Hover Tank": "120x92"\n}\n', encoding="utf-8")
    disp = Path(__file__).parent / "demo_images" / "dispositions"
    if disp.is_dir():  # same placeholder disposition icons as the monsters
        (OUT / "dispositions").mkdir(exist_ok=True)
        for p in disp.glob("*.png"):
            (OUT / "dispositions" / p.name).write_bytes(p.read_bytes())


if __name__ == "__main__":
    main()
