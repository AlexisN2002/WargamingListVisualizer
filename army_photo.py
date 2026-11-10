#!/usr/bin/env python3
"""
army-photo: turn a New Recruit army list into a "group photo" of your army.

Every model in the list is placed on one picture: a unit of 20 is shown with
20 copies of the model, leaders stand in front of the unit they lead, big
monsters stand in the back row. You supply the model images.

Quick start:
    python army_photo.py my_list.txt
    python army_photo.py                 # reads the list from the clipboard

See README.md for the full documentation.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

__version__ = "1.0.0"

IMAGE_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
OUTPUT_PREFIXES = ("army_photo", "group_photo")
CONFIG_NAME = "army.json"

DEFAULTS = {
    "max_model_height": 1400,   # tallest model is scaled down to at most this many pixels
    "background": "#ffffff",    # or "transparent"
    "margin": 70,
    "overlap": 110,             # how much neighbouring units overlap (pixels)
    "shadow_opacity": 55,       # 0-255, soft shadow under each unit
    "disposition_size": 0.16,   # disposition icon height relative to image height
    "disposition_position": "top-left",  # top-left, top-right, bottom-left, bottom-right
    "placeholders": False,      # draw "?" for models without an image
}

DISPOSITIONS = ["take and hold", "disruption", "purge the foe", "priority assets", "reconnaissance"]


# --------------------------------------------------------------------------- #
# List parsing
# --------------------------------------------------------------------------- #
UNIT_RE = re.compile(r"^(?P<name>[^•◦].*?)\s*\((?P<points>[\d,.]+)\s*(?:Points|pts|Punkte)\)\s*$", re.I)
COUNT_RE = re.compile(r"^\s*[•\-*]\s*(\d+)x\s+(.+?)\s*$")
SUB_RE = re.compile(r"^\s*◦")
ATTACHED_GROUP_RE = re.compile(r"^Attached unit\s*(\d+)", re.I)


@dataclass
class Unit:
    id: int
    name: str
    points: int
    models: int = 0
    warlord: bool = False
    enhancement: str = ""
    character: bool = False
    attached_group: int | None = None
    attached_role: str = ""  # "leader" or "bodyguard"


@dataclass
class ArmyList:
    title: str = ""
    points: str = ""
    faction: str = ""
    detachment: str = ""
    disposition: str = ""
    units: list[Unit] = field(default_factory=list)
    has_attachments: bool = False


def _is_section(line: str) -> bool:
    s = line.strip()
    return bool(s) and s.upper() == s and any(c.isalpha() for c in s) and "(" not in s


def _to_int(text: str) -> int:
    return int(re.sub(r"[^\d]", "", text) or 0)


def parse_list(text: str) -> ArmyList:
    """Parse a New Recruit text export ("Copy as text")."""
    lines = [l.rstrip() for l in text.splitlines()]
    army = ArmyList()
    header = [l.strip() for l in lines if l.strip()]
    if header:
        m = UNIT_RE.match(header[0])
        army.title = m.group("name") if m else header[0]
        army.points = m.group("points") if m else ""

    section = None
    unit = None
    group = None
    header_lines = []
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.lower().startswith("exported with"):
            continue
        if _is_section(s):
            section, unit = s, None
            continue
        if section is None:
            header_lines.append(s)
            continue
        g = ATTACHED_GROUP_RE.match(s)
        if g:
            army.has_attachments = True
            group, unit = int(g.group(1)), None
            continue
        if "ATTACHED" not in section.upper():
            group = None
        m = UNIT_RE.match(s)
        if m:
            unit = Unit(id=len(army.units), name=m.group("name").strip(), points=_to_int(m.group("points")),
                        character="CHARACTER" in section.upper(), attached_group=group)
            army.units.append(unit)
            continue
        if unit is None:
            continue
        content = s.lstrip("•◦-* ").strip()
        low = content.lower()
        if low.startswith("attached as"):
            role = content.split(":", 1)[-1].strip().lower()
            unit.attached_role = "leader" if role.startswith("leader") else "bodyguard"
            if unit.attached_role == "leader":
                unit.character = True
        elif low == "warlord":
            unit.warlord = True
        elif low.startswith("enhancement"):
            unit.enhancement = content.split(":", 1)[-1].strip()
        c = COUNT_RE.match(raw)
        if c and not SUB_RE.match(raw):
            nxt = next((lines[j] for j in range(i + 1, len(lines)) if lines[j].strip()), "")
            if SUB_RE.match(nxt):  # a model entry has indented ◦ weapon lines below it
                unit.models += int(c.group(1))

    # header: title, faction, detachment, disposition, battle size
    rest = header_lines[1:]
    if rest:
        army.faction = rest[0]
    if len(rest) > 1:
        army.detachment = re.sub(r"\s*\(.*\)$", "", rest[1])
    for line in rest[2:]:
        if disposition_index(line) is not None:
            army.disposition = line
            break
    for u in army.units:
        u.models = u.models or 1
    return army


# --------------------------------------------------------------------------- #
# Image lookup
# --------------------------------------------------------------------------- #
def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def base_key(filename: str) -> str:
    """'hormagaunt-2023-a.webp' -> 'hormagaunt' (drops years and variant suffixes)."""
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[-_ ](19|20)\d\d(?=$|[-_ ])", "", stem)
    while True:
        new = re.sub(r"[-_ ]([a-z]|\d+)$", "", stem)
        if new == stem:
            break
        stem = new
    return slug(stem)


def name_candidates(name: str) -> list[str]:
    out = []
    variants = [name, re.split(r"\s+with\s+", name, flags=re.I)[0], re.sub(r"^the\s+", "", name, flags=re.I)]
    for v in variants:
        k = slug(v)
        for c in (k, k[:-1] if k.endswith("s") else k, k[:-2] if k.endswith("es") else k):
            if c and c not in out:
                out.append(c)
    return out


class ImageLibrary:
    def __init__(self, folder: Path, aliases: dict):
        self.folder = folder
        self.aliases = aliases
        self.index: dict[str, list[Path]] = {}
        for p in sorted(folder.iterdir()) if folder.is_dir() else []:
            if p.suffix.lower() in IMAGE_EXTENSIONS and not p.stem.lower().startswith(OUTPUT_PREFIXES + ("dispo",)):
                self.index.setdefault(base_key(p.name), []).append(p)
        self._cache: dict[Path, Image.Image] = {}
        self._scaled: dict[tuple, Image.Image] = {}

    def find(self, name: str) -> list[Path]:
        if name in self.aliases:
            v = self.aliases[name]
            v = v if isinstance(v, list) else [v]
            return [self.folder / x for x in v if (self.folder / x).exists()]
        cands = name_candidates(name)
        for k in cands:
            if k in self.index:
                return self.index[k]
        for k in cands:  # e.g. "neurogaunt" -> neurogaunt-a-node-beast.webp
            hits = sorted((s for s in self.index if s.startswith(k)), key=len)
            if hits:
                return self.index[hits[0]]
        for k in cands:
            hit = difflib.get_close_matches(k, self.index.keys(), n=1, cutoff=0.82)
            if hit:
                return self.index[hit[0]]
        return []

    def load(self, path: Path) -> Image.Image:
        if path not in self._cache:
            im = Image.open(path).convert("RGBA")
            # remove near-invisible leftovers from background removal
            im.putalpha(im.getchannel("A").point(lambda a: 0 if a < 40 else a))
            box = im.getchannel("A").getbbox()
            self._cache[path] = im.crop(box) if box else im
        return self._cache[path]

    def model(self, path: Path, height: int, flip=False, darken=0) -> Image.Image:
        key = (path, height, flip, darken)
        if key not in self._scaled:
            im = self.load(path)
            f = height / im.height
            im = im.resize((max(1, int(im.width * f)), max(1, int(height))), Image.LANCZOS)
            if flip:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            if darken:
                shade = Image.new("RGBA", im.size, (10, 5, 15, 0))
                shade.putalpha(im.getchannel("A").point(lambda a: a * darken // 255))
                im = Image.alpha_composite(im, shade)
            self._scaled[key] = im
        return self._scaled[key]


def placeholder(height: int) -> Image.Image:
    w = int(height * 0.6)
    im = Image.new("RGBA", (w, int(height)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([2, 2, w - 3, height - 3], int(w * 0.2), fill=(200, 200, 205, 220),
                        outline=(150, 150, 160), width=3)
    d.text((w / 2, height / 2), "?", fill=(110, 110, 120), anchor="mm")
    return im


# --------------------------------------------------------------------------- #
# Dispositions
# --------------------------------------------------------------------------- #
def disposition_index(text: str | None) -> int | None:
    k = slug(text or "")
    for i, n in enumerate(DISPOSITIONS):
        if k and (k == slug(n) or k.rstrip("s") == slug(n).rstrip("s")):
            return i
    return None


def _remove_light_background(img: Image.Image) -> Image.Image:
    """Flood-fill the light, colourless background from the edges and make it transparent."""
    img = img.convert("RGBA")
    w, h = img.size
    hsv = img.convert("HSV")
    S, V = hsv.getchannel("S").load(), hsv.getchannel("V").load()
    mask = Image.new("L", (w, h), 0)
    M = mask.load()
    for y in range(h):
        for x in range(w):
            if S[x, y] < 45 and V[x, y] > 150:
                M[x, y] = 255
    edge = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    for x, y in edge:
        if M[x, y] == 255:
            ImageDraw.floodfill(mask, (x, y), 128, thresh=0)
    alpha = mask.point(lambda v: 0 if v == 128 else 255)
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    img.putalpha(alpha)
    box = alpha.point(lambda a: 255 if a > 128 else 0).getbbox()
    return img.crop(box) if box else img


def extract_disposition_sheet(path: Path) -> list[Image.Image]:
    """Cut the 5 coloured icons out of a disposition reference card.

    Expects the icons stacked vertically in the right part of the image, in the
    order of DISPOSITIONS (top to bottom).
    """
    im = Image.open(path).convert("RGB")
    W, H = im.size
    x0 = int(W * 0.6)
    part = im.crop((x0, 0, W, H))
    sat = part.convert("HSV").getchannel("S").load()
    pw, ph = part.size
    rows = [sum(1 for x in range(pw) if sat[x, y] > 70) for y in range(ph)]
    bands, start = [], None
    for y, v in enumerate(rows + [0]):
        if v > 3 and start is None:
            start = y
        if v <= 3 and start is not None:
            if y - start > 15:
                bands.append((start, y))
            start = None
    icons = []
    for a, b in bands:
        cols = [sum(1 for y in range(a, b) if sat[x, y] > 70) >= 5 for x in range(pw)]
        best, st = (0, 0), None
        for x, v in enumerate(cols + [False]):
            if v and st is None:
                st = x
            if not v and st is not None:
                if x - st > best[1] - best[0]:
                    best = (st, x)
                st = None
        box = (x0 + best[0] - 6, max(0, a - 8), x0 + best[1] + 6, min(H, b + 9))
        icons.append(_remove_light_background(im.crop(box)))
    return icons


def find_disposition_icon(folder: Path, disposition: str) -> Image.Image | None:
    idx = disposition_index(disposition)
    if idx is None:
        return None
    # 1) single icon files: <images>/dispositions/priority-assets.png
    d = folder / "dispositions"
    if d.is_dir():
        for p in d.iterdir():
            if p.suffix.lower() in IMAGE_EXTENSIONS and disposition_index(p.stem.replace("-", " ").replace("_", " ")) == idx:
                return Image.open(p).convert("RGBA")
    # 2) a reference card: <images>/dispositions.jpg (or dispos.*)
    sheet = next((p for p in sorted(folder.iterdir()) if p.stem.lower().startswith("dispo")
                  and p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS), None) if folder.is_dir() else None
    if sheet:
        icons = extract_disposition_sheet(sheet)
        if len(icons) == len(DISPOSITIONS):
            return icons[idx]
        print(f"Note: found {len(icons)} instead of {len(DISPOSITIONS)} icons in {sheet.name}, skipping.")
    return None


def paste_disposition(photo: Image.Image, icon: Image.Image, cfg: dict) -> None:
    h = int(min(max(160, photo.height * cfg["disposition_size"]), icon.height * 5))
    icon = icon.resize((int(icon.width * h / icon.height), h), Image.LANCZOS)
    m = int(h * 0.25)
    pos = cfg["disposition_position"]
    x = photo.width - icon.width - m if "right" in pos else m
    y = photo.height - icon.height - m if "bottom" in pos else m
    photo.alpha_composite(icon, (x, y))


# --------------------------------------------------------------------------- #
# Leaders
# --------------------------------------------------------------------------- #
def resolve_leaders(army: ArmyList, presets: dict[str, str], ask: bool) -> dict[int, int]:
    """Return {leader unit id: led unit id}."""
    result: dict[int, int] = {}
    # 1) "ATTACHED UNITS" section of the export
    for c in army.units:
        if c.attached_role == "leader" and c.attached_group is not None:
            t = next((t for t in army.units if t.attached_group == c.attached_group
                      and t.attached_role != "leader"), None)
            if t:
                result[c.id] = t.id
    chars = [u for u in army.units if u.character]
    squads = [u for u in army.units if not u.character]
    # 2) presets from --leader / army.json
    taken = set()
    for c in chars:
        if c.id in result:
            continue
        for leader, target in presets.items():
            if slug(c.name).startswith(slug(leader)):
                t = next((t for t in squads if slug(t.name) == slug(target) and t.id not in taken), None)
                if t:
                    result[c.id] = t.id
                    taken.add(t.id)
                    break
    # 3) ask (only when the export has no attachment info)
    open_chars = [c for c in chars if c.id not in result]
    if army.has_attachments or not ask or not open_chars or not squads or not sys.stdin.isatty():
        return result
    print("\nWhich characters lead a unit?")
    for i, t in enumerate(squads, 1):
        print(f"  {i}) {t.name}")
    for c in open_chars:
        try:
            answer = input(f"{c.name} leads (number, Enter = nobody): ").strip()
        except EOFError:
            break
        if answer.isdigit() and 1 <= int(answer) <= len(squads):
            result[c.id] = squads[int(answer) - 1].id
    return result


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
class Renderer:
    def __init__(self, lib: ImageLibrary, cfg: dict, scale_overrides: dict):
        self.lib = lib
        self.cfg = cfg
        self.overrides = scale_overrides
        self.scale = 1.0
        self.missing: list[str] = []

    def images_for(self, unit: Unit) -> list[Path]:
        imgs = self.lib.find(unit.name)
        if not imgs and unit.name not in self.missing:
            self.missing.append(unit.name)
        return imgs

    def height_for(self, unit: Unit, imgs: list[Path]) -> int:
        """Images are expected to share one scale, so we keep their native size."""
        if imgs:
            h = self.lib.load(imgs[0]).height * self.scale
        else:  # rough guess from points per model
            h = 62 * max(1, unit.points / unit.models) ** 0.42 * self.scale
        return max(1, int(h * self.overrides.get(unit.name, 1.0)))

    def draw_group(self, squad: Unit, leaders: list[Unit]) -> Image.Image:
        rnd = random.Random(squad.name)
        imgs = self.images_for(squad)
        h = self.height_for(squad, imgs)
        n = squad.models
        sample = self.lib.load(imgs[0]) if imgs else None
        model_w = (sample.width / sample.height * h) if sample else h * 0.6
        spacing = model_w * (0.55 if n > 1 else 1)
        cols = n if n <= 6 else max(5, math.ceil(math.sqrt(n * 2.2)))
        rows = math.ceil(n / cols)
        depth = h * 0.32

        pieces = []  # (x centre, ground y, image)
        for r in range(rows):
            in_row = min(cols, n - r * cols)
            back = rows - 1 - r
            s = 1 - 0.07 * back
            darken = int(70 * back / max(1, rows - 1)) if rows > 1 else 0
            ground = -back * depth
            shift = spacing / 2 if back % 2 else 0
            for c in range(in_row):
                x = (c - (in_row - 1) / 2) * spacing * s + shift + rnd.uniform(-6, 6)
                if imgs:
                    im = self.lib.model(imgs[(r * cols + c) % len(imgs)], int(h * s), rnd.random() < 0.4, darken)
                else:
                    im = placeholder(int(h * s))
                pieces.append((x, ground + rnd.uniform(-4, 4), im))

        for i, ld in enumerate(leaders):
            li = self.images_for(ld)
            lh = self.height_for(ld, li)
            im = self.lib.model(li[0], lh) if li else placeholder(lh)
            x = (i - (len(leaders) - 1) / 2) * im.width * 0.9
            pieces.append((x, depth * 0.45, im))

        min_x = min(x - im.width / 2 for x, _, im in pieces)
        max_x = max(x + im.width / 2 for x, _, im in pieces)
        min_y = min(y - im.height for _, y, im in pieces)
        max_y = max(y for _, y, _ in pieces)
        P = 60
        W, H = int(max_x - min_x) + 2 * P, int(max_y - min_y) + 2 * P
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if self.cfg["shadow_opacity"]:
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(sh).ellipse([P, H - P - max(30, depth * rows * 0.8), W - P, H - P + 15],
                                       fill=(0, 0, 0, int(self.cfg["shadow_opacity"])))
            canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
        for x, y, im in sorted(pieces, key=lambda t: t[1]):
            canvas.alpha_composite(im, (int(x - im.width / 2 - min_x + P), int(y - im.height - min_y + P)))
        return canvas


def _center_out(items: list) -> list:
    left, right = [], []
    for i, it in enumerate(items):
        (right if i % 2 == 0 else left).append(it)
    return list(reversed(left)) + right


def _parse_color(value: str):
    if value == "transparent":
        return (255, 255, 255, 0)
    v = value.lstrip("#")
    if len(v) == 6:
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    raise ValueError(f"Unknown colour: {value}")


def render(army: ArmyList, lib: ImageLibrary, cfg: dict, leaders: dict[int, int],
           scale_overrides: dict) -> tuple[Image.Image, list[str]]:
    by_id = {u.id: u for u in army.units}
    groups = []
    skipped = []
    for u in army.units:
        if u.id in leaders:
            continue
        led_by = [by_id[c] for c, t in leaders.items() if t == u.id]
        if not cfg["placeholders"]:
            kept = []
            for l in led_by:
                (kept if lib.find(l.name) else skipped).append(l)
            led_by = kept
            if not lib.find(u.name):
                skipped.append(u)
                if not led_by:
                    continue
                u, led_by = led_by[0], led_by[1:]
        groups.append((u, led_by))

    r = Renderer(lib, cfg, scale_overrides)
    heights = [lib.load(p[0]).height for sq, ls in groups for un in [sq] + ls for p in [lib.find(un.name)] if p]
    r.scale = min(1.0, cfg["max_model_height"] / max(heights)) if heights else 1.0
    pictures = [r.draw_group(sq, ls) for sq, ls in groups]
    if not pictures:
        raise SystemExit("No images found for any unit. Check the --images folder and file names.")

    # rows like a group photo: tall units in the back, small ones in front
    pictures.sort(key=lambda b: b.height, reverse=True)
    area = sum(b.width * b.height for b in pictures)
    max_w = max(max(b.width for b in pictures) * 1.4, math.sqrt(area) * 1.7)
    gap = -int(cfg["overlap"])
    rows, cur, w = [], [], 0
    for b in pictures:
        if cur and w + gap + b.width > max_w:
            rows.append(cur)
            cur, w = [], 0
        cur.append(b)
        w += (gap if w else 0) + b.width
    if cur:
        rows.append(cur)

    placed, ground = [], 0
    for i, row in enumerate(rows):
        row = _center_out(row)
        rw = sum(b.width for b in row) + gap * (len(row) - 1)
        if i:
            ground += max(60, int(max(b.height for b in row) * 0.35))
        placed.append((row, ground, rw))

    top = min(g - max(b.height for b in row) for row, g, _ in placed)
    bottom = max(g for _, g, _ in placed)
    M = int(cfg["margin"])
    W = int(max(rw for _, _, rw in placed)) + 2 * M
    H = int(bottom - top) + 2 * M
    photo = Image.new("RGBA", (W, H), _parse_color(cfg["background"]))
    for row, g, rw in placed:
        x = (W - rw) / 2
        base = g - top + M
        for b in row:
            photo.alpha_composite(b, (int(x), int(base - b.height)))
            x += b.width + gap

    missing = list(dict.fromkeys(r.missing + [u.name for u in skipped]))
    return photo, missing


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def read_clipboard() -> str:
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return text
    except Exception:
        return ""


def save(img: Image.Image, target: Path) -> Path:
    """Save; if the file is locked (e.g. still open in a viewer) use a numbered name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    for t in [target] + [target.with_name(f"{target.stem}_{i}{target.suffix}") for i in range(2, 100)]:
        try:
            img.save(t)
            if t != target:
                print(f"Note: {target.name} is locked (open somewhere?), saved as {t.name} instead.")
            return t
        except OSError:
            continue
    raise OSError(f"Could not save {target}")


def find_image_folder(explicit: str | None, faction: str) -> Path:
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve().parent
    fs = slug(faction)
    for base in (Path.cwd(), here):
        root = base / "images"
        if root.is_dir() and fs:
            for d in root.iterdir():
                if d.is_dir() and slug(d.name) == fs:
                    return d
    for base in (Path.cwd(), here):
        if (base / "images").is_dir():
            return base / "images"
    return here


def load_config(folder: Path) -> dict:
    p = folder / CONFIG_NAME
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="army-photo",
                                 description="Turn a New Recruit army list into a group photo of your models.")
    ap.add_argument("list", nargs="?", help="text file with the list (default: clipboard)")
    ap.add_argument("-o", "--output", help="output file (default: army_photo_<list name>.png)")
    ap.add_argument("-i", "--images", help="folder with model images (default: images/<faction>)")
    ap.add_argument("-l", "--leader", action="append", default=[], metavar="CHARACTER=UNIT",
                    help='attach a leader, e.g. "Tyranid Prime=Hormagaunts" (repeatable)')
    ap.add_argument("--no-questions", action="store_true", help="never ask which unit a character leads")
    ap.add_argument("--background", help='"#ffffff", "#000000", "transparent", ...')
    ap.add_argument("--transparent", action="store_true", help="shortcut for --background transparent")
    ap.add_argument("--max-height", type=int, help="height of the tallest model in pixels")
    ap.add_argument("--placeholders", action="store_true", help='show "?" for models without an image')
    ap.add_argument("--no-disposition", action="store_true", help="do not add the disposition icon")
    ap.add_argument("--extract-dispositions", metavar="CARD",
                    help="cut the 5 icons out of a disposition card into <images>/dispositions/ and exit")
    ap.add_argument("--no-open", action="store_true", help="do not open the result afterwards")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    if args.extract_dispositions:
        folder = Path(args.images) if args.images else Path(args.extract_dispositions).resolve().parent
        out = folder / "dispositions"
        out.mkdir(parents=True, exist_ok=True)
        icons = extract_disposition_sheet(Path(args.extract_dispositions))
        if len(icons) != len(DISPOSITIONS):
            print(f"Found {len(icons)} icons, expected {len(DISPOSITIONS)}.")
            return 1
        for name, icon in zip(DISPOSITIONS, icons):
            icon.save(out / f"{name.replace(' ', '-')}.png")
        print(f"Saved {len(icons)} icons to {out}")
        return 0

    if args.list:
        text = Path(args.list).read_text(encoding="utf-8")
    else:
        text = read_clipboard()
        if not any(UNIT_RE.match(l.strip()) for l in (text or "").splitlines()):
            print("No army list in the clipboard. Paste it here, then press "
                  "Ctrl+Z and Enter (Windows) or Ctrl+D (macOS/Linux):")
            text = sys.stdin.read()
        else:
            print("Read army list from clipboard.")
    army = parse_list(text)
    if not army.units:
        print("No units found - is this a New Recruit text export?")
        return 1

    folder = find_image_folder(args.images, army.faction)
    conf = load_config(folder)
    cfg = {**DEFAULTS, **conf.get("settings", {})}
    if args.background:
        cfg["background"] = args.background
    if args.transparent:
        cfg["background"] = "transparent"
    if args.max_height:
        cfg["max_model_height"] = args.max_height
    if args.placeholders:
        cfg["placeholders"] = True

    presets = dict(conf.get("leaders", {}))
    presets.update(dict(a.split("=", 1) for a in args.leader if "=" in a))
    leaders = resolve_leaders(army, presets, ask=not args.no_questions)

    lib = ImageLibrary(folder, conf.get("images", {}))
    print(f"Using images from: {folder}")
    photo, missing = render(army, lib, cfg, leaders, conf.get("scale", {}))

    if not args.no_disposition and army.disposition:
        icon = find_disposition_icon(folder, army.disposition)
        if icon is not None:
            paste_disposition(photo, icon, cfg)

    target = Path(args.output) if args.output else folder / f"army_photo_{slug(army.title) or 'army'}.png"
    out = photo if cfg["background"] == "transparent" else photo.convert("RGB")
    target = save(out, target)
    print(f"\nSaved: {target}")
    if missing:
        print("No image found (left out):", ", ".join(missing))
        print(f"Tip: name the file after the unit (e.g. '{slug(missing[0])}.png') or add it to {CONFIG_NAME}.")
    if not args.no_open and sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    sys.exit(main())
