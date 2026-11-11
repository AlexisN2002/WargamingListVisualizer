"""
Deployment board for army-photo (version 3).

Puts one or two army lists on a 44" x 60" battlefield (seen from above, like the
mission cards): every model is a token with its real base size, standing in its
army's deployment zone. Optionally the official terrain layout image is used as
the background.

Coordinates are in inches, origin top-left, x along the 44" edge, y along the
60" edge (portrait, like the Warhammer 40,000 11th edition deployment cards).
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import army_photo as ap

BOARD_W, BOARD_H = 44.0, 60.0
MM_PER_INCH = 25.4
OBJECTIVE_MM = 40.0

ARMY_COLORS = [(178, 34, 34), (25, 70, 125)]   # attacker red, defender blue
ZONE_ALPHA = 200
PAPER = (226, 222, 212)
GRID = (205, 200, 190)
GRID_6 = (180, 175, 165)

# --------------------------------------------------------------------------- #
# Deployment maps (Warhammer 40,000 11th edition, Chapter Approved 2026-27).
# a = attacker (red), b = defender (blue). poly = zone outline, cut = circles
# (x, y, radius) that are not part of the zone. objectives: centre first, then
# the two home objectives (a, b), then the expansion objectives.
# --------------------------------------------------------------------------- #
MAPS: dict[str, dict] = {
    "tipping-point": {
        "a": {"poly": [(0, 0), (44, 0), (44, 12), (22, 12), (22, 20), (0, 20)]},
        "b": {"poly": [(44, 60), (0, 60), (0, 48), (22, 48), (22, 40), (44, 40)]},
        "objectives": [(22, 30), (11, 14), (33, 46), (38, 24), (6, 36)],
    },
    "sweeping-engagement": {
        "a": {"poly": [(0, 0), (14, 0), (14, 30), (8, 30), (8, 60), (0, 60)]},
        "b": {"poly": [(44, 0), (44, 60), (30, 60), (30, 30), (36, 30), (36, 0)]},
        "objectives": [(22, 30), (10, 14), (34, 46), (30, 10), (14, 50)],
    },
    "search-and-destroy": {
        "a": {"poly": [(0, 0), (22, 0), (22, 30), (0, 30)], "cut": [(22, 30, 9)]},
        "b": {"poly": [(22, 30), (44, 30), (44, 60), (22, 60)], "cut": [(22, 30, 9)]},
        "objectives": [(22, 30), (10, 14), (34, 46), (34, 14), (10, 46)],
    },
    "hammer-and-anvil": {
        "a": {"poly": [(0, 0), (44, 0), (44, 18), (0, 18)]},
        "b": {"poly": [(0, 42), (44, 42), (44, 60), (0, 60)]},
        "objectives": [(22, 30), (10, 14), (34, 46), (36, 24), (8, 36)],
    },
    "dawn-of-war": {
        "a": {"poly": [(0, 0), (12, 0), (12, 60), (0, 60)]},
        "b": {"poly": [(32, 0), (44, 0), (44, 60), (32, 60)]},
        "objectives": [(22, 30), (10, 30), (34, 30), (25, 10), (19, 50)],
    },
    "crucible-of-battle": {
        "a": {"poly": [(0, 0), (44, 0), (0, 30)]},
        "b": {"poly": [(44, 60), (0, 60), (44, 30)]},
        "objectives": [(22, 30), (10, 12), (34, 48), (34, 15), (10, 45)],
    },
}

# --------------------------------------------------------------------------- #
# Terrain layouts: any layout images in images/layouts (e.g. the official ones from the
# Warhammer Event Companion). You pick one from a menu; the deployment map is read from the
# image. The images belong to their owners and are not part of this repository.
# --------------------------------------------------------------------------- #
def layouts_folder() -> Path:
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        if (base / "images").is_dir():
            return base / "images" / "layouts"
    return Path(__file__).resolve().parent / "images" / "layouts"


def layout_label(path: Path) -> str:
    """'43_Take_and_Hold_vs_Take_and_Hold_Layout_A.png' -> 'Take and Hold vs Take and Hold, Layout A'."""
    name = re.sub(r"^\d+[_ -]*", "", path.stem).replace("_", " ")
    return re.sub(r"\s+Layout\s+([A-Z])$", r", Layout \1", name)


def layout_index(maps: dict, folder: Path | None = None) -> dict[str, str]:
    """{file name: deployment map} for every layout image, cached in layouts/index.json."""
    folder = folder or layouts_folder()
    if not folder.is_dir():
        return {}
    cache_file = folder / "index.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in ap.IMAGE_EXTENSIONS)
    index, changed = {}, False
    for p in files:
        key = f"{p.name}|{p.stat().st_size}"
        if key not in cache:
            raw = Image.open(p)
            cache[key] = detect_map(flatten(raw), find_board_rect(raw), maps) or ""
            changed = True
        if cache[key]:
            index[p.name] = cache[key]
    if changed:
        try:
            cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        except OSError:
            pass
    return index


def _ask(prompt: str, n: int) -> int | None:
    """Number between 1 and n, or None for Enter."""
    try:
        a = input(prompt).strip()
    except EOFError:
        return None
    return int(a) if a.isdigit() and 1 <= int(a) <= n else None


def choose_battlefield(maps: dict, map_name: str, layout: str, seed) -> tuple[str, Path | None]:
    """Deployment map and terrain layout image. layout: "ask", "random", "none", a number or a file."""
    folder = layouts_folder()
    index = layout_index(maps, folder) if layout != "none" else {}
    rnd = random.Random(seed)
    # a layout given directly: number ("43"), file name or path
    if layout not in ("ask", "random", "none", ""):
        p = Path(layout)
        if not p.exists():
            hits = [f for f in index if f.startswith(layout.zfill(2) + "_") or f.lower() == layout.lower()]
            p = folder / hits[0] if hits else p
        if p.exists():
            raw = Image.open(p)
            return detect_map(flatten(raw), find_board_rect(raw), maps) or map_name or list(maps)[0], p
        print(f"Layout '{layout}' not found, choosing without it.")
        layout = "ask"
    interactive = sys.stdin.isatty() and (layout == "ask" or map_name in ("", "ask"))
    names = list(maps)
    if index and layout != "none":
        # only the maps that have a terrain layout
        names = [n for n in names if n in index.values()] or names
    if map_name not in maps:
        if interactive:
            print("\nWhich deployment map?")
            for i, n in enumerate(names, 1):
                k = sum(1 for m in index.values() if m == n)
                print(f"  {i}) {n.replace('-', ' ').title()}" + (f"  ({k} terrain layouts)" if k else ""))
            pick = _ask("Number (Enter = random): ", len(names))
            map_name = names[pick - 1] if pick else rnd.choice(names)
        else:
            map_name = rnd.choice(names)
    options = sorted(f for f, m in index.items() if m == map_name)
    if layout == "none" or not options:
        return map_name, None
    if len(options) == 1:  # one layout per map: no need to ask
        return map_name, folder / options[0]
    if layout == "ask" and sys.stdin.isatty():
        print(f"\nWhich terrain layout for {map_name.replace('-', ' ').title()}?")
        print("  0) No terrain")
        for i, f in enumerate(options, 1):
            print(f"  {i}) {layout_label(Path(f))}")
        try:
            a = input("Number (Enter = random): ").strip()
        except EOFError:
            a = ""
        if a == "0":
            return map_name, None
        if a.isdigit() and 1 <= int(a) <= len(options):
            return map_name, folder / options[int(a) - 1]
    return map_name, folder / rnd.choice(options)


ROUND_BASES = [25, 28.5, 32, 40, 50, 60, 80, 90, 100, 130, 160]
OVAL_BASES = [(60, 35), (75, 42), (90, 52), (105, 70), (120, 92), (170, 105)]


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #
def _in_poly(x: float, y: float, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xc = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xc:
                inside = not inside
    return inside


def zone_contains(zone: dict, x: float, y: float, rx: float = 0.0, ry: float = 0.0) -> bool:
    """True if the ellipse (x, y, rx, ry) lies inside the zone (sampled on its outline)."""
    pts = [(x, y)] + [(x + rx * math.cos(a), y + ry * math.sin(a)) for a in
                      (i * math.pi / 6 for i in range(12))] if (rx or ry) else [(x, y)]
    for px, py in pts:
        if not (0 <= px <= BOARD_W and 0 <= py <= BOARD_H) or not _in_poly(px, py, zone["poly"]):
            return False
    for cx, cy, r in zone.get("cut", []):
        if math.hypot(x - cx, y - cy) < r + max(rx, ry):
            return False
    return True


def zone_centroid(zone: dict) -> tuple[float, float]:
    pts = [(x + 0.5, y + 0.5) for x in range(int(BOARD_W)) for y in range(int(BOARD_H))
           if zone_contains(zone, x + 0.5, y + 0.5)]
    if not pts:
        return BOARD_W / 2, BOARD_H / 2
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def load_maps(*folders: Path) -> dict:
    """Built-in maps, plus/overridden by maps.json files in the given folders."""
    maps = {k: v for k, v in MAPS.items()}
    for f in folders:
        p = Path(f) / "maps.json"
        if p.exists():
            for name, m in json.loads(p.read_text(encoding="utf-8")).items():
                maps[name.lower().replace(" ", "-")] = m
    return maps


# --------------------------------------------------------------------------- #
# Base sizes
# --------------------------------------------------------------------------- #
def parse_base(value) -> tuple[float, float] | None:
    """25 -> (25, 25); "105x70" -> (105, 70); "32mm" -> (32, 32)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value), float(value)
    m = re.match(r"^\s*([\d.]+)\s*(?:mm)?\s*(?:[x×]\s*([\d.]+)\s*(?:mm)?)?\s*$", str(value), re.I)
    if not m:
        return None
    w = float(m.group(1))
    h = float(m.group(2)) if m.group(2) else w
    return max(w, h), min(w, h)


class Bases:
    """Base sizes per unit or model name, read from bases.json files."""

    def __init__(self, *files: Path):
        self.table: dict[str, tuple[float, float]] = {}
        for f in files:
            if f and Path(f).exists():
                data = json.loads(Path(f).read_text(encoding="utf-8"))
                for k, v in data.items():
                    b = parse_base(v)
                    if b and not k.startswith("_"):
                        self.table["".join(ap.name_words(k))] = b

    def get(self, *names: str) -> tuple[float, float] | None:
        for n in names:
            if not n:
                continue
            key = "".join(ap.name_words(n))
            if key in self.table:
                return self.table[key]
        return None


def snap_base(mm: float) -> tuple[float, float]:
    best = min(ROUND_BASES, key=lambda b: abs(b - mm))
    return best, best


# --------------------------------------------------------------------------- #
# Terrain layout images
# --------------------------------------------------------------------------- #
def flatten(img: Image.Image) -> Image.Image:
    """Transparent parts on white (the official layouts are PNGs with a transparent background)."""
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    bg.alpha_composite(rgba)
    return bg.convert("RGB")


def _longest_block(flags: list[bool]) -> tuple[int, int] | None:
    best, start = None, None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        if not f and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i - 1)
            start = None
    return best


def find_board_rect(img: Image.Image) -> tuple[int, int, int, int]:
    """Find the battlefield inside a layout image. Transparent layouts: the biggest opaque block.
    Others: the area framed by the long dark border lines."""
    if img.mode in ("RGBA", "LA", "P"):
        a = img.convert("RGBA").getchannel("A")
        if a.getextrema()[0] < 128:
            W, H = a.size
            small = a.resize((max(1, W // 4), max(1, H // 4)))
            sw, sh = small.size
            px = small.load()
            rows = [sum(1 for x in range(sw) if px[x, y] > 128) > 0.6 * sw for y in range(sh)]
            cols = [sum(1 for y in range(sh) if px[x, y] > 128) > 0.6 * sh for x in range(sw)]
            rb, cb = _longest_block(rows), _longest_block(cols)
            if rb and cb:
                f = W / sw
                x0, y0, x1, y1 = int(cb[0] * f), int(rb[0] * f), int((cb[1] + 1) * f), int((rb[1] + 1) * f)
                # trim the dark frame around the battlefield
                g = flatten(img).convert("L")
                def dark_col(x): return sum(g.getpixel((x, y)) for y in range(y0, y1, 8)) / len(range(y0, y1, 8)) < 60
                def dark_row(y): return sum(g.getpixel((x, y)) for x in range(x0, x1, 8)) / len(range(x0, x1, 8)) < 60
                while x0 < x1 - 10 and dark_col(x0): x0 += 1
                while x1 > x0 + 10 and dark_col(x1 - 1): x1 -= 1
                while y0 < y1 - 10 and dark_row(y0): y0 += 1
                while y1 > y0 + 10 and dark_row(y1 - 1): y1 -= 1
                return x0, y0, x1, y1
    g = img.convert("L")
    W, H = g.size
    small = g.resize((W // 2, H // 2)) if W > 1200 else g
    sw, sh = small.size
    px = small.load()

    def longest_dark_run(coords):
        best = run = 0
        for x, y in coords:
            if px[x, y] < 70:
                run += 1
                best = max(best, run)
            else:
                run = 0
        return best

    rows = [y for y in range(sh) if longest_dark_run(((x, y) for x in range(sw))) > 0.45 * sw]
    cols = [x for x in range(sw) if longest_dark_run(((x, y) for y in range(sh))) > 0.45 * sh]
    f = W / sw
    if len(rows) >= 2 and len(cols) >= 2:
        return int(min(cols) * f), int(min(rows) * f), int(max(cols) * f), int(max(rows) * f)
    return 0, 0, W, H  # no border found: the whole image is the battlefield


def _zone_mask_score(img: Image.Image, rect, zone: dict, color: str) -> float:
    x0, y0, x1, y1 = rect
    rgb = img.convert("RGB")
    hits = total = 0
    for gx in (x + 0.5 for x in range(0, 44, 2)):          # between the grid lines
        for gy in (y + 0.5 for y in range(0, 60, 2)):
            if not zone_contains(zone, gx, gy):
                continue
            px = x0 + (x1 - x0) * gx / BOARD_W
            py = y0 + (y1 - y0) * gy / BOARD_H
            r, g, b = rgb.getpixel((int(px), int(py)))
            total += 1
            if color == "red" and r > g + 40 and r > b + 40:
                hits += 1
            if color == "blue" and b > r + 30:
                hits += 1
    return hits / total if total else 0


def detect_map(img: Image.Image, rect, maps: dict) -> str | None:
    """Guess the deployment map of a layout image from its red and blue zones."""
    best, best_score = None, 0.0
    for name, m in maps.items():
        s = _zone_mask_score(img, rect, m["a"], "red") + _zone_mask_score(img, rect, m["b"], "blue")
        if s > best_score:
            best, best_score = name, s
    return best if best_score > 1.2 else None


def terrain_mask(img: Image.Image, rect) -> Image.Image:
    """4 px per inch, white where the layout image shows terrain: the grey footprints (neutral grey,
    a bit cooler than the beige battlefield) and the green walls."""
    from PIL import ImageFilter
    W, H = int(BOARD_W * 4), int(BOARD_H * 4)
    board = img.convert("RGB").crop(rect).resize((W, H), Image.BILINEAR)
    mask = Image.new("L", (W, H), 0)
    src, dst = board.load(), mask.load()
    for y in range(H):
        for x in range(W):
            r, g, b = src[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            grey = (mx - mn) < 22 and (b - r) > -5 and 120 <= mx <= 235
            green = g > r + 20 and g > b + 5
            if grey or green:
                dst[x, y] = 255
    return mask.filter(ImageFilter.MedianFilter(5))


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
@dataclass
class Model:
    path: Path | None
    base: tuple[float, float]          # mm (long, short)
    unit: ap.Unit
    estimated: bool = False


@dataclass
class Token:
    x: float
    y: float
    model: Model
    army: int


def _radius(m: Model) -> tuple[float, float]:
    return m.base[0] / MM_PER_INCH / 2, m.base[1] / MM_PER_INCH / 2


def cluster(models: list[Model], spacing: float = 0.2) -> list[tuple[float, float]]:
    """Offsets (inches) for the models of one unit: packed as tightly as their bases allow,
    the first models (the leaders) in the middle, the blob a bit wider than deep."""
    placed: list[tuple[float, float, float]] = []
    out = []
    total = sum((m.base[0] / MM_PER_INCH) ** 2 for m in models)
    R = math.sqrt(total) * 1.6 + 2
    step = 0.2
    n = int(R / step)
    grid = sorted(((math.hypot(i * step, j * step * 1.4), i * step, j * step)
                   for i in range(-n, n + 1) for j in range(-n, n + 1)))
    for m in models:
        r = m.base[0] / MM_PER_INCH / 2
        for _, x, y in grid:
            if all(math.hypot(x - px, y - py) >= r + pr + spacing for px, py, pr in placed):
                placed.append((x, y, r))
                out.append((x, y))
                break
    return out


def place_army(groups: list[list[Model]], zone: dict, army: int, occupied: list[Token],
               terrain: Image.Image | None, seed: int = 0, enemy: tuple[float, float] | None = None,
               smart: float = 1.0) -> tuple[list[Token], list[str]]:
    """Put every unit (list of models) into the zone. Big units go to the back, small ones to the
    front, spread out sideways. With a terrain layout the units deploy "smart": infantry likes to
    stand in the ruins, and everybody likes a spot where terrain blocks the view to the enemy.
    Big models (60 mm bases and up) stay out of the ruins. Returns the tokens and the names of
    units that didn't fit."""
    cx, cy = zone_centroid(zone)
    fx, fy = BOARD_W / 2 - cx, BOARD_H / 2 - cy          # towards the middle of the table
    fl = math.hypot(fx, fy) or 1
    fx, fy = fx / fl, fy / fl
    lx, ly = -fy, fx                                      # sideways
    cands = [(x / 2, y / 2) for x in range(0, int(BOARD_W * 2) + 1) for y in range(0, int(BOARD_H * 2) + 1)
             if zone_contains(zone, x / 2, y / 2)]
    if not cands:
        return [], [g[0].unit.name for g in groups]
    depth = {c: (c[0] - cx) * fx + (c[1] - cy) * fy for c in cands}      # + = front
    side = {c: (c[0] - cx) * lx + (c[1] - cy) * ly for c in cands}
    half = max(abs(v) for v in side.values()) or 1
    rnd = random.Random(seed)

    def terrain_share(x, y, rx, ry):
        if terrain is None:
            return 0.0
        px, py = int(x * 4), int(y * 4)
        r = max(1, int(max(rx, ry) * 4))
        box = terrain.crop((px - r, py - r, px + r, py + r))
        return box.histogram()[255] / max(1, box.size[0] * box.size[1])

    ex, ey = enemy if enemy else (BOARD_W / 2, BOARD_H / 2)

    def hidden(c):
        """1 if terrain lies on the line from c towards the enemy (between 1.5" and 14")."""
        if terrain is None:
            return 0.0
        dx, dy = ex - c[0], ey - c[1]
        dist = math.hypot(dx, dy) or 1
        hits = 0
        for k in range(3, 29):
            t = k * 0.5
            if t > dist:
                break
            px, py = int((c[0] + dx / dist * t) * 4), int((c[1] + dy / dist * t) * 4)
            if 0 <= px < terrain.width and 0 <= py < terrain.height and terrain.getpixel((px, py)):
                hits += 1
        return 1.0 if hits >= 3 else hits / 3

    cover = {c: hidden(c) for c in cands} if terrain is not None and smart else {c: 0.0 for c in cands}

    tokens: list[Token] = []
    missing: list[str] = []
    order = sorted(groups, key=lambda g: max(m.base[0] for m in g), reverse=True)
    targets = [0.0] + [s * k / 3 for k in (1, 2, 3) for s in (1, -1)]
    for gi, g in enumerate(order):
        big = max(m.base[0] for m in g) >= 60
        target = targets[gi % len(targets)] * half
        offs = cluster(g)
        # big units prefer the back of the zone, small ones the front; all spread sideways.
        # smart: a spot behind terrain is worth a few inches, infantry also likes to stand in ruins
        spread = max(abs(x) for x, _ in offs) + 1 if offs else 1

        def key(c, big=big, target=target, spread=spread):
            k = (depth[c] if big else -depth[c]) + 0.5 * abs(side[c] - target) + rnd.random() * 0.3
            if terrain is not None and smart:
                k -= smart * 6 * cover[c]
                if not big:
                    k -= smart * 5 * terrain_share(c[0], c[1], spread * 0.7, spread * 0.7)
            return k
        placed = False
        for avoid_terrain in (True, False):
            for c in sorted(cands, key=key):
                ok = True
                for (ox, oy), m in zip(offs, g):
                    x, y = c[0] + ox, c[1] + oy
                    rx, ry = _radius(m)
                    if not zone_contains(zone, x, y, rx, ry):
                        ok = False
                        break
                    if avoid_terrain and (big or not smart) and terrain_share(x, y, rx, ry) > 0.35:
                        ok = False
                        break
                    for t in occupied + tokens:
                        trx, _ = _radius(t.model)
                        gap = 0.15 if t.model.unit is m.unit else 1.0
                        if math.hypot(t.x - x, t.y - y) < rx + trx + gap:
                            ok = False
                            break
                    if not ok:
                        break
                if ok:
                    tokens += [Token(c[0] + ox, c[1] + oy, m, army) for (ox, oy), m in zip(offs, g)]
                    placed = True
                    break
            if placed:
                break
        if not placed:
            missing.append(g[0].unit.name)
    return tokens, missing


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
def _font(size: int):
    for n in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_board(maps_entry: dict, ppi: float) -> Image.Image:
    W, H = int(BOARD_W * ppi), int(BOARD_H * ppi)
    img = Image.new("RGBA", (W, H), PAPER + (255,))
    zones = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    zd = ImageDraw.Draw(zones)
    for key, col in (("a", ARMY_COLORS[0]), ("b", ARMY_COLORS[1])):
        z = maps_entry[key]
        zd.polygon([(x * ppi, y * ppi) for x, y in z["poly"]], fill=col + (ZONE_ALPHA,))
        for cx, cy, r in z.get("cut", []):
            zd.ellipse([(cx - r) * ppi, (cy - r) * ppi, (cx + r) * ppi, (cy + r) * ppi], fill=(0, 0, 0, 0))
    img.alpha_composite(zones)
    d = ImageDraw.Draw(img)
    for i in range(int(BOARD_W) + 1):
        d.line([(i * ppi, 0), (i * ppi, H)], fill=(GRID_6 if i % 6 == 0 else GRID) + (110,), width=1)
    for j in range(int(BOARD_H) + 1):
        d.line([(0, j * ppi), (W, j * ppi)], fill=(GRID_6 if j % 6 == 0 else GRID) + (110,), width=1)
    for k in range(0, W, int(ppi * 0.6)):  # dotted centre lines
        d.ellipse([k, H / 2 - 2, k + 3, H / 2 + 1], fill=(40, 40, 40))
    for k in range(0, H, int(ppi * 0.6)):
        d.ellipse([W / 2 - 2, k, W / 2 + 1, k + 3], fill=(40, 40, 40))
    r = OBJECTIVE_MM / MM_PER_INCH / 2 * ppi
    for i, (ox, oy) in enumerate(maps_entry.get("objectives", [])):
        ring = ARMY_COLORS[0] if i == 1 else ARMY_COLORS[1] if i == 2 else (20, 120, 90)
        d.ellipse([ox * ppi - r, oy * ppi - r, ox * ppi + r, oy * ppi + r], fill=(245, 245, 240), outline=ring,
                  width=max(2, int(r * 0.25)))
    d.rectangle([0, 0, W - 1, H - 1], outline=(20, 20, 20), width=max(2, int(ppi / 12)))
    return img


def _initials(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", name)[:3]).upper() or "?"


def draw_token(canvas: Image.Image, t: Token, ppi: float, lib: ap.ImageLibrary, style: str,
               model_scale: float) -> None:
    """style 'tokens': the model image inside a round/oval base. style 'models': the base on the
    table with the model standing on it (true scale)."""
    col = ARMY_COLORS[t.army]
    rw = t.model.base[0] / MM_PER_INCH / 2 * ppi
    rh = t.model.base[1] / MM_PER_INCH / 2 * ppi
    cx, cy = t.x * ppi, t.y * ppi
    ring = max(2, int(min(rw, rh) * 0.12))
    d = ImageDraw.Draw(canvas)
    if style == "models":
        # just the model photo, all images with one shared scale (they are drawn to scale),
        # standing with its feet on the spot of its base
        if t.model.path is not None:
            src = lib.load(t.model.path)
            w = max(1, int(src.width * model_scale))
            h = max(1, int(src.height * model_scale))
            im = src.resize((w, h), Image.LANCZOS)
            canvas.alpha_composite(im, (int(cx - w / 2), int(cy + rh * 0.6 - h)))
        else:  # no image: a plain base in the army colour
            d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(55, 50, 45, 255), outline=col + (255,), width=ring)
        return
    # tokens: white disc, coloured ring, the model fitted inside
    d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(250, 248, 244, 255), outline=col + (255,), width=ring)
    inner_w, inner_h = int(2 * (rw - ring) * 0.92), int(2 * (rh - ring) * 0.92)
    if t.model.path is not None and inner_w > 2 and inner_h > 2:
        src = lib.load(t.model.path)
        f = min(inner_w / src.width, inner_h / src.height) * 1.12
        im = src.resize((max(1, int(src.width * f)), max(1, int(src.height * f))), Image.LANCZOS)
        mask = Image.new("L", (int(2 * rw), int(2 * rh)), 0)
        ImageDraw.Draw(mask).ellipse([ring, ring, 2 * rw - ring, 2 * rh - ring], fill=255)
        layer = Image.new("RGBA", mask.size, (0, 0, 0, 0))
        layer.alpha_composite(im, (int(rw - im.width / 2), int(rh - im.height / 2)))
        a = layer.getchannel("A")
        layer.putalpha(Image.composite(a, Image.new("L", a.size, 0), mask))
        canvas.alpha_composite(layer, (int(cx - rw), int(cy - rh)))
    else:
        f = _font(max(8, int(min(rw, rh) * 0.7)))
        txt = _initials(t.model.unit.name)
        tw = d.textlength(txt, font=f)
        d.text((cx - tw / 2, cy - min(rw, rh) * 0.45), txt, font=f, fill=col + (255,))


# --------------------------------------------------------------------------- #
# Putting it together
# --------------------------------------------------------------------------- #
@dataclass
class ArmySetup:
    army: ap.ArmyList
    folder: Path
    cfg: dict
    lib: ap.ImageLibrary
    renderer: ap.Renderer
    leaders: dict
    bases: Bases
    groups: list = field(default_factory=list)   # list[list[Model]]


def unit_models(s: ArmySetup, unit: ap.Unit) -> list[Model]:
    paths = s.renderer.model_images(unit)
    groups = unit.groups or [ap.ModelGroup(unit.models, unit.name)]
    if sum(g.count for g in groups) < len(paths):
        groups = [ap.ModelGroup(len(paths), unit.name)]
    names = [g.name for g in groups for _ in range(g.count)]
    out = []
    for p, n in zip(paths, names):
        b = s.bases.get(n, unit.name)
        out.append(Model(p, b or (0, 0), unit, estimated=b is None))
    return out


def build_groups(s: ArmySetup) -> None:
    by_id = {u.id: u for u in s.army.units}
    for u in s.army.units:
        if u.id in s.leaders:
            continue
        led = [by_id[c] for c, t in s.leaders.items() if t == u.id]
        models = [m for l in led for m in unit_models(s, l)] + unit_models(s, u)
        s.groups.append(models)


def estimate_bases(setups: list[ArmySetup]) -> list[str]:
    """Fill in missing base sizes from the image width (images share one scale)."""
    ratios = []
    for s in setups:
        for g in s.groups:
            for m in g:
                if not m.estimated and m.path is not None:
                    ratios.append(m.base[0] / max(1, s.lib.load(m.path).width))
    ratio = sorted(ratios)[len(ratios) // 2] if ratios else None
    guessed = []
    for s in setups:
        for g in s.groups:
            for m in g:
                if m.estimated:
                    if m.path is not None and ratio:
                        m.base = snap_base(s.lib.load(m.path).width * ratio * 0.8)
                    else:
                        m.base = (32.0, 32.0)
                    if m.unit.name not in guessed:
                        guessed.append(m.unit.name)
    return guessed


def model_image_scale(setups: list[ArmySetup], ppi: float) -> float:
    """Image pixels -> board pixels for the 'models' style. All images share one scale, so one
    factor for everything: taken from the small and medium models (base width vs. image width),
    because their photos are about as wide as their bases."""
    ratios = []
    for s in setups:
        for g in s.groups:
            for m in g:
                if m.path is not None and not m.estimated and m.base[0] <= 60:
                    ratios.append(m.base[0] / max(1, s.lib.load(m.path).width))
    if not ratios:
        ratios = [m.base[0] / max(1, s.lib.load(m.path).width)
                  for s in setups for g in s.groups for m in g if m.path is not None] or [0.1]
    mm_per_px = sorted(ratios)[len(ratios) // 2]
    return mm_per_px / MM_PER_INCH * ppi


def render_board(setups: list[ArmySetup], map_name: str, maps: dict, style: str = "tokens",
                 ppi: float = 30, terrain_image: Path | None = None, seed: int = 0):
    m = maps[map_name]
    terrain = None
    if terrain_image is not None:
        raw = Image.open(terrain_image)
        rect = find_board_rect(raw)
        bg = flatten(raw).convert("RGBA")
        ppi = (rect[2] - rect[0]) / BOARD_W
        terrain = terrain_mask(bg, rect)
        canvas = bg
        offset = (rect[0], rect[1])
    else:
        canvas = draw_board(m, ppi)
        offset = (0, 0)

    tokens: list[Token] = []
    missing: list[str] = []
    for i, s in enumerate(setups[:2]):
        zone = m["a" if i == 0 else "b"]
        enemy = zone_centroid(m["b" if i == 0 else "a"])
        t, miss = place_army(s.groups, zone, i, tokens, terrain, seed=seed + i, enemy=enemy,
                             smart=float(s.cfg.get("smart_deploy", 1.0)))
        tokens += t
        missing += miss

    scale = model_image_scale(setups, ppi)
    if style == "models" and terrain_image is None:
        # models stick out above the battlefield: add some room at the top
        top = max([int(s.lib.load(m.path).height * scale)
                   for s in setups for g in s.groups for m in g if m.path] + [0])
        top = min(top, int(ppi * 8))
        framed = Image.new("RGBA", (canvas.width, canvas.height + top), (255, 255, 255, 255))
        framed.alpha_composite(canvas, (0, top))
        canvas, offset = framed, (0, top)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    libs = {i: s.lib for i, s in enumerate(setups)}
    pad = int(ppi * 8)  # models can stick out of the battlefield
    sub = Image.new("RGBA", (int(BOARD_W * ppi) + 2 * pad, int(BOARD_H * ppi) + 2 * pad), (0, 0, 0, 0))
    for t in sorted(tokens, key=lambda t: t.y):   # back to front
        draw_token(sub, Token(t.x + pad / ppi, t.y + pad / ppi, t.model, t.army), ppi, libs[t.army], style, scale)
    layer.alpha_composite(sub, (offset[0] - pad, offset[1] - pad))
    canvas.alpha_composite(layer)
    return canvas, missing


def ask_map(maps: dict) -> str:  # kept for compatibility
    names = list(maps)
    if not sys.stdin.isatty():
        return names[0]
    print("\nWhich deployment map?")
    for i, n in enumerate(names, 1):
        print(f"  {i}) {n.replace('-', ' ').title()}")
    try:
        a = input("Number (Enter = 1): ").strip()
    except EOFError:
        a = ""
    return names[int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(names) else names[0]


def run(texts: list[str], args) -> int:
    """Entry point used by army_photo.main() for --board."""
    setups: list[ArmySetup] = []
    for n, text in enumerate(texts[:2]):
        army = ap.parse_list(text)
        if not army.units:
            print(f"List {n + 1}: no units found.")
            return 1
        print(f"List {n + 1}: {army.title or army.faction} ({ap.FORMAT_NAMES.get(army.format, army.format)}, "
              f"{len(army.units)} units)")
        folder = ap.find_image_folder(args.images if n == 0 else getattr(args, "enemy_images", None),
                                      army.faction)
        conf = ap.load_config(folder)
        cfg = {**ap.DEFAULTS, **conf.get("settings", {}), "no_disposition": args.no_disposition}
        presets = dict(conf.get("leaders", {}))
        if n == 0:
            presets.update(dict(a.split("=", 1) for a in args.leader if "=" in a))
        if len(texts) > 1 and not army.has_attachments:
            print(f"Leaders for {army.title or army.faction}:")
        leaders = ap.resolve_leaders(army, presets, ask=not args.no_questions)
        lib = ap.ImageLibrary(folder, conf.get("images", {}))
        r = ap.Renderer(lib, cfg, conf.get("scale", {}))
        bases = Bases(folder / "bases.json", Path(args.bases) if args.bases else None)
        s = ArmySetup(army, folder, cfg, lib, r, leaders, bases)
        build_groups(s)
        setups.append(s)

    maps = load_maps(*[s.folder for s in setups])
    map_name = (args.map or "").lower().replace(" ", "-")
    layout = "none" if args.no_terrain else (args.terrain or "none")
    map_name, terrain = choose_battlefield(maps, map_name, layout, args.seed)
    print(f"Deployment map: {map_name.replace('-', ' ').title()}"
          + (f"  -  terrain: {layout_label(terrain)}" if terrain else ""))

    if args.board_style == "ask":
        args.board_style = "tokens"
        if sys.stdin.isatty():
            print("\nHow should the models look?\n  1) Tokens: round bases with the model inside\n"
                  "  2) Models: standing on their bases")
            try:
                if input("Number (Enter = 1): ").strip() == "2":
                    args.board_style = "models"
            except EOFError:
                pass

    guessed = estimate_bases(setups)
    if guessed:
        print("No base size in bases.json for:", ", ".join(guessed))
        print("      (estimated from the image; add them to bases.json, e.g. \"Termagants\": 25)")

    photo, missing = render_board(setups, map_name, maps, style=args.board_style, ppi=args.ppi,
                                  terrain_image=terrain, seed=args.seed or 0)
    names = "_vs_".join(ap.slug(s.army.title or s.army.faction) or "army" for s in setups)
    target = Path(args.output) if args.output else setups[0].folder / f"army_board_{names}.png"
    target = ap.save(photo.convert("RGB"), target)
    print(f"\nSaved: {target}")
    if missing:
        print("No room in the deployment zone for:", ", ".join(missing))
    for s in setups:
        if s.renderer.missing:
            print(f"No image found ({s.army.title or s.army.faction}):", ", ".join(s.renderer.missing))
    if not args.no_open and sys.platform.startswith("win"):
        import os
        os.startfile(target)  # type: ignore[attr-defined]
    return 0
