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

__version__ = "3.0.0"

IMAGE_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
OUTPUT_PREFIXES = ("army_photo", "group_photo")
CONFIG_NAME = "army.json"

DEFAULTS = {
    "max_model_height": 1400,   # tallest model is scaled down to at most this many pixels
    "background": "#ffffff",    # or "transparent"
    "margin": 70,
    "overlap": 110,             # how much neighbouring units overlap (pixels)
    "shadow_opacity": 0,        # 0-255, soft shadow under each unit (off by default)
    "disposition_size": 0.16,   # disposition icon height relative to image height
    "disposition_position": "top-left",  # top-left, top-right, bottom-left, bottom-right
    "placeholders": False,      # draw "?" for models without an image
    "layout": "group-photo",    # "group-photo" (packed) or "battle-ready" (spread out, hero in the middle)
    "perspective": 0.18,        # battle-ready: how much smaller units get further back (0 = off)
    "tilt": 0.65,               # battle-ready: how much higher units stand further back
    "curve": 0.15,              # battle-ready: how strongly the rows bend backwards at the sides
    "max_hidden": 0.01,         # battle-ready: a unit is moved back until at most this much of it is hidden
    "smart_deploy": 1.0,        # board: how much units like to stand in / behind terrain (0 = off)
}

DISPOSITIONS = ["take and hold", "disruption", "purge the foe", "priority assets", "reconnaissance"]


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class ModelGroup:
    """Models of one kind inside a unit, e.g. '2x Hive Guard: Impaler cannon'."""
    count: int
    name: str
    wargear: list[str] = field(default_factory=list)


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
    wargear: list[str] = field(default_factory=list)   # unit-level options / weapons
    groups: list[ModelGroup] = field(default_factory=list)

    def hints(self) -> list[str]:
        """Everything that can help to pick the right image variant."""
        h = list(self.wargear)
        for g in self.groups:
            h.append(g.name)
            h.extend(g.wargear)
        m = re.search(r"\s+with\s+(.+)$", self.name, re.I)
        if m:
            h.append(m.group(1))
        return h


@dataclass
class ArmyList:
    title: str = ""
    points: str = ""
    faction: str = ""
    detachment: str = ""
    disposition: str = ""
    units: list[Unit] = field(default_factory=list)
    has_attachments: bool = False
    format: str = ""
    has_model_counts: bool = True
    links: list[tuple[int, int]] = field(default_factory=list)  # (leader id, led unit id)


# --------------------------------------------------------------------------- #
# List parsing - shared helpers
# --------------------------------------------------------------------------- #
def _to_int(text: str) -> int:
    return int(re.sub(r"[^\d]", "", text) or 0)


def _split_items(text: str) -> list[str]:
    """'Warlord, Bone Sabres, Rupture cannon [20 pts]' -> ['Warlord', 'Bone Sabres', 'Rupture cannon']"""
    items = []
    for part in re.split(r",\s*(?![^\[(]*[\])])", text or ""):
        part = re.sub(r"\s*[\[(][^\])]*(?:pts|points|upgrade)[^\])]*[\])]", "", part, flags=re.I).strip(" .:")
        if part:
            items.append(part)
    return items


def _apply_items(unit: Unit, items: list[str]) -> None:
    for it in items:
        it = re.sub(r"^\d+\s+with\s+", "", it)  # "10 with Genestealer claws" -> "Genestealer claws"
        low = it.lower()
        if low == "warlord":
            unit.warlord = True
        elif low.startswith("enhancement"):
            unit.enhancement = it.split(":", 1)[-1].strip()
        else:
            unit.wargear.append(it)


def _is_section(line: str) -> bool:
    s = line.strip()
    return bool(s) and s.upper() == s and any(c.isalpha() for c in s) and "(" not in s and "[" not in s


def _faction_line(line: str) -> tuple[str, str, str, str] | None:
    """'Xenos - Tyranids - CrusherTalons - [1990 pts]' -> (faction, rest, title, points)."""
    m = re.match(r"^(?P<parts>.+?)(?:\s+-\s+\[(?P<pts>[\d,.]+)\s*pts\])?\s*$", line.strip())
    parts = [p.strip() for p in m.group("parts").split(" - ")] if m else []
    if len(parts) < 2:
        return None
    faction = parts[1] if len(parts) >= 2 else parts[0]
    rest = " - ".join(parts[2:])
    pts = m.group("pts") or ""
    title = rest if pts else ""
    return faction, rest, title, pts


# --------------------------------------------------------------------------- #
# Format 1: GW style ("Tyranid Prime (75 Points)" + bullet lists)
# --------------------------------------------------------------------------- #
GW_UNIT_RE = re.compile(r"^(?P<name>[^•◦].*?)\s*\((?P<points>[\d,.]+)\s*(?:Points|Punkte)\)\s*$", re.I)
BULLET_RE = re.compile(r"^\s*[•\-*]\s*(?:(\d+)x\s+)?(.+?)\s*$")
SUB_RE = re.compile(r"^\s*◦\s*(?:(\d+)x\s+)?(.+?)\s*$")
ATTACHED_GROUP_RE = re.compile(r"^Attached unit\s*(\d+)", re.I)


def parse_gw(text: str) -> ArmyList:
    lines = [l.rstrip() for l in text.splitlines()]
    army = ArmyList(format="gw")
    section = unit = group = None
    header = []
    current_group: ModelGroup | None = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.lower().startswith("exported with"):
            continue
        if _is_section(s):
            section, unit = s, None
            continue
        if section is None:
            header.append(s)
            continue
        g = ATTACHED_GROUP_RE.match(s)
        if g:
            army.has_attachments = True
            group, unit = int(g.group(1)), None
            continue
        if "ATTACHED" not in section.upper():
            group = None
        m = GW_UNIT_RE.match(s)
        if m:
            unit = Unit(id=len(army.units), name=m.group("name").strip(), points=_to_int(m.group("points")),
                        character="CHARACTER" in section.upper() or "EPIC HERO" in section.upper(),
                        attached_group=group)
            army.units.append(unit)
            current_group = None
            continue
        if unit is None:
            continue
        sub = SUB_RE.match(raw)
        if sub:
            if current_group is not None:
                current_group.wargear.append(sub.group(2))
            else:
                unit.wargear.append(sub.group(2))
            continue
        b = BULLET_RE.match(raw)
        if not b:
            continue
        content = b.group(2)
        low = content.lower()
        if low.startswith("attached as"):
            role = content.split(":", 1)[-1].strip().lower()
            unit.attached_role = "leader" if role.startswith("leader") else "bodyguard"
            if unit.attached_role == "leader":
                unit.character = True
            continue
        if low == "warlord":
            unit.warlord = True
            continue
        if low.startswith("enhancement"):
            unit.enhancement = content.split(":", 1)[-1].strip()
            continue
        nxt = next((lines[j] for j in range(i + 1, len(lines)) if lines[j].strip()), "")
        if b.group(1) and SUB_RE.match(nxt):  # a model entry has indented ◦ weapon lines below it
            current_group = ModelGroup(int(b.group(1)), content)
            unit.groups.append(current_group)
        else:
            current_group = None
            unit.wargear.append(content)

    if header:
        m = GW_UNIT_RE.match(header[0])
        army.title = m.group("name") if m else header[0]
        army.points = m.group("points") if m else ""
    rest = header[1:]
    if rest:
        army.faction = rest[0]
    if len(rest) > 1:
        army.detachment = re.sub(r"\s*\(.*\)$", "", rest[1])
    return army


# --------------------------------------------------------------------------- #
# Format 2: compact ("Char1: 1x The Swarmlord (210 pts): Warlord, Bone Sabres")
# --------------------------------------------------------------------------- #
COMPACT_UNIT_RE = re.compile(
    r"^(?:(?P<char>Char\d+)\s*:\s*)?(?P<n>\d+)x\s+(?P<name>.+?)\s*\((?P<points>[\d,.]+)\s*pts\)\s*(?::\s*(?P<rest>.*))?$",
    re.I)


COMPACT_GROUP_RE = re.compile(r"^[•\-*]\s*(?P<n>\d+)x\s+(?P<name>[^:]+?)\s*(?::\s*(?P<rest>.*))?$")
COMPACT_WITH_RE = re.compile(r"^(?P<n>\d+)\s+with\s+(?P<rest>.+)$", re.I)
COMPACT_LINK_RE = re.compile(r"^(?P<kind>leading|attached to)\s*:?\s+(?P<name>.+)$", re.I)


def parse_compact(text: str) -> ArmyList:
    army = ArmyList(format="compact")
    header = []
    unit = None
    group: ModelGroup | None = None
    split_group = False   # the current group was already split into "3 with ..." / "1 with ..."
    pending: list[tuple[str, int, str]] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("created with", "exported with")):
            continue
        m = COMPACT_UNIT_RE.match(s)
        if m:
            unit = Unit(id=len(army.units), name=m.group("name").strip(), points=_to_int(m.group("points")),
                        character=bool(m.group("char")))
            rest = m.group("rest") or ""
            items = _split_items(rest)
            counts = [int(c) for c in re.findall(r"(?:^|,\s*)(\d+)x\s", rest)]
            n = int(m.group("n"))
            unit.models = max([n] + counts)
            _apply_items(unit, [re.sub(r"^\d+x\s+", "", it) for it in items])
            army.units.append(unit)
            group, split_group = None, False
            continue
        if unit is None:
            if not army.units:
                header.append(s)
            continue
        if s.lower().startswith("enhancement"):
            unit.enhancement = re.sub(r"\s*\(.*\)$", "", s.split(":", 1)[-1]).strip()
            continue
        lk = COMPACT_LINK_RE.match(s)  # "Leading Genestealers[1]" / "Attached to Broodlord[1]"
        if lk:
            kind = "leads" if lk.group("kind").lower().startswith("leading") else "led_by"
            pending.append((kind, unit.id, lk.group("name")))
            continue
        g = COMPACT_GROUP_RE.match(s)  # "• 4x Ravener" / "• 1x Ravener Prime: Warlord, Prime claws"
        if g:
            items = _split_items(g.group("rest") or "")
            if any(i.lower() == "warlord" for i in items):
                unit.warlord = True
            group = ModelGroup(int(g.group("n")), g.group("name").strip(),
                               [i for i in items if i.lower() != "warlord"])
            unit.groups.append(group)
            split_group = False
            continue
        w = COMPACT_WITH_RE.match(s)  # "3 with Ravener heavy claws and talons"
        if w and group is not None:
            sub = ModelGroup(int(w.group("n")), group.name, group.wargear + _split_items(w.group("rest")))
            if not split_group:  # replace the parent group by its parts
                unit.groups.remove(group)
                split_group = True
            unit.groups.append(sub)
            continue

    if header:
        m = GW_UNIT_RE.match(header[0])
        army.title = m.group("name") if m else header[0]
        army.points = m.group("points") if m else ""
    if len(header) > 1:
        army.faction = header[1]
    if len(header) > 2:
        army.detachment = re.sub(r"\s*\(.*\)$", "", header[2])
    _link_by_name(army, pending)
    return army


# --------------------------------------------------------------------------- #
# Format 3: simple ("Norn Emissary (270pts): Destabilising Predation (Upgrade)")
# --------------------------------------------------------------------------- #
SIMPLE_UNIT_RE = re.compile(r"^(?P<name>[^•◦#].*?)\s*\((?P<points>[\d,.]+)\s*pts\)\s*(?::\s*(?P<rest>.*))?$", re.I)


SIMPLE_ATTACHED_RE = re.compile(r"^\+\s*(?:(?P<n>\d+)x\s+)?(?P<unit>.+)$")


def parse_simple(text: str) -> ArmyList:
    army = ArmyList(format="simple", has_model_counts=False)
    leader = None
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("created with", "exported with")):
            continue
        a = SIMPLE_ATTACHED_RE.match(s)  # "+ 6x Zoanthropes (190pts)" = unit led by the line above
        m = SIMPLE_UNIT_RE.match(a.group("unit") if a else s)
        if m:
            unit = Unit(id=len(army.units), name=m.group("name").strip(), points=_to_int(m.group("points")))
            _apply_items(unit, _split_items(m.group("rest") or ""))
            army.units.append(unit)
            if a:
                unit.models = int(a.group("n") or 0)
                if leader is not None:
                    leader.character = True
                    army.links.append((leader.id, unit.id))
                    army.has_attachments = True
            else:
                leader = unit
            continue
        if not army.units and not army.faction:
            fl = _faction_line(s)
            if fl:
                army.faction, army.detachment, army.title, army.points = fl
    return army


# --------------------------------------------------------------------------- #
# Format 4: bracket / roster ("Exocrine [135 pts]: Bio-plasmic cannon" and
#           "# ++ Army Roster ++" with "## Monster [1580 pts]" sections)
# --------------------------------------------------------------------------- #
BRACKET_UNIT_RE = re.compile(r"^(?P<name>[^•◦#].*?)\s*\[(?P<points>[\d,.]+)\s*pts\]\s*(?::\s*(?P<rest>.*))?$", re.I)
BRACKET_MODEL_RE = re.compile(r"^\s*[•\-*]\s*(\d+)x\s+(?P<name>[^:]+?)\s*(?::\s*(?P<rest>.*))?$")
LINK_RE = re.compile(r"^\s*[•\-*+]?\s*(?P<kind>leading|leads|attached to|leader|led by)\s*:\s*(?P<name>.+?)\s*$", re.I)


def _link_by_name(army: ArmyList, pending: list[tuple[str, int, str]]) -> None:
    """Turn ('leads', unit id, other name) / ('led_by', unit id, other name) into army.links."""
    for kind, uid, other in pending:
        m = re.match(r"^(.*?)\s*\[(\d+)\]\s*$", other)  # "Genestealers[2]" = the 2nd Genestealers unit
        name, idx = (m.group(1), int(m.group(2))) if m else (other, None)
        cands = [u for u in army.units if slug(u.name) == slug(name) and u.id != uid]
        if idx is not None:
            cands = cands[idx - 1:idx]
        if kind == "leads":
            taken = {t for _, t in army.links}
            t = next((u for u in cands if u.id not in taken), None)
            pair = (uid, t.id) if t else None
        else:
            done = {l for l, _ in army.links}
            l = next((u for u in cands if u.id not in done), None)
            pair = (l.id, uid) if l else None
        if pair and pair not in army.links and pair[0] not in {l for l, _ in army.links}:
            army.links.append(pair)
            army.units[pair[0]].character = True
            army.has_attachments = True


def parse_bracket(text: str) -> ArmyList:
    army = ArmyList(format="roster" if re.search(r"^#\s*\+\+", text, re.M) else "bracket")
    section = ""
    unit = None
    counted = False
    pending: list[tuple[str, int, str]] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("created with", "exported with")):
            continue
        lk = LINK_RE.match(raw)
        if lk and unit is not None:  # "• Leading: Zoanthropes" / "• Leader: Neurotyrant"
            kind = "leads" if lk.group("kind").lower() in ("leading", "leads", "attached to") else "led_by"
            pending.append((kind, unit.id, lk.group("name")))
            continue
        if s.startswith("#"):
            section = s.lstrip("# ").strip()
            unit = None
            continue
        if s.lower().startswith("force disposition:"):
            army.disposition = s.split(":", 1)[1].strip()
            continue
        if s.lower().startswith("detachment") and ":" in s:
            army.detachment = ", ".join(re.sub(r"\s*\[.*?\]", "", p).strip()
                                        for p in s.split(":", 1)[1].split(","))
            continue
        if ":" in s and not BRACKET_UNIT_RE.match(s) and unit is None and section.lower().startswith("config"):
            continue
        fl = _faction_line(s) if " - " in s and not army.units else None
        if fl and (fl[3] or not army.faction):
            army.faction, rest, title, pts = fl
            army.title = title or army.title
            army.points = pts or army.points
            continue
        mm = BRACKET_MODEL_RE.match(raw)
        if mm and unit is not None:
            g = ModelGroup(int(mm.group(1)), mm.group("name").strip(), _split_items(mm.group("rest") or ""))
            unit.groups.append(g)
            counted = True
            continue
        m = BRACKET_UNIT_RE.match(s)
        if m:
            unit = Unit(id=len(army.units), name=m.group("name").strip(), points=_to_int(m.group("points")),
                        character=any(k in section.lower() for k in ("character", "epic hero", "hq")))
            _apply_items(unit, _split_items(m.group("rest") or ""))
            army.units.append(unit)
    army.has_model_counts = counted or army.format == "roster"
    _link_by_name(army, pending)
    return army


# --------------------------------------------------------------------------- #
# Format detection
# --------------------------------------------------------------------------- #
def detect_format(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if any(BRACKET_UNIT_RE.match(l) and not l.startswith("#") and " - [" not in l for l in lines):
        return "bracket"
    if any(_is_section(l) for l in lines) and sum(bool(GW_UNIT_RE.match(l)) for l in lines) >= 2:
        return "gw"
    if any(COMPACT_UNIT_RE.match(l) for l in lines):
        return "compact"
    if any(SIMPLE_UNIT_RE.match(l) for l in lines):
        return "simple"
    return "gw"


def parse_list(text: str) -> ArmyList:
    """Parse a New Recruit text export (all export styles are detected automatically)."""
    fmt = detect_format(text)
    army = {"gw": parse_gw, "compact": parse_compact, "simple": parse_simple, "bracket": parse_bracket}[fmt](text)
    if not army.disposition:
        for line in text.splitlines():
            if disposition_index(line.strip()) is not None:
                army.disposition = line.strip()
                break
    for u in army.units:
        if u.groups:
            u.models = sum(g.count for g in u.groups)
        u.models = u.models or 1
    return army


# --------------------------------------------------------------------------- #
# Image lookup
# --------------------------------------------------------------------------- #
STOP_WORDS = {"the", "of", "and", "a", "an", "with"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def stem(word: str) -> str:
    w = slug(word)
    if len(w) > 5 and w.endswith("ed"):
        w = w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


def words(text: str) -> list[str]:
    return [stem(w) for w in re.split(r"[\s\-_']+", text.lower().replace("'s", "s")) if slug(w)]


def name_words(name: str) -> list[str]:
    """'Tyranid Prime with Lash Whip' -> ['tyranid', 'prime']"""
    base = re.split(r"\s+with\s+", name, flags=re.I)[0]
    return [w for w in words(base) if w not in STOP_WORDS]


@dataclass
class ImageFile:
    path: Path
    tokens: list[str]        # stemmed words of the file name
    variant_at: int | None   # index of a variant marker like "-a" / "-2", if any


def parse_filename(path: Path) -> ImageFile:
    tokens, variant_at = [], None
    for raw in re.split(r"[\s\-_]+", path.stem.lower()):
        if not raw:
            continue
        if re.fullmatch(r"(19|20)\d\d", raw):        # year: ignore
            continue
        if re.fullmatch(r"[a-z]|\d+", raw):          # variant marker: -a, -b, -2
            if variant_at is None:
                variant_at = len(tokens)
            continue
        tokens.append(stem(raw))
    return ImageFile(path, [t for t in tokens if t not in STOP_WORDS], variant_at)


def _match_name(name: list[str], tokens: list[str]) -> set[int] | None:
    """Indexes of file tokens used by the unit name, or None if the name isn't in the file name."""
    used: set[int] = set()
    for w in name:
        hit = None
        for i in range(len(tokens)):
            if i in used:
                continue
            if tokens[i] == w:
                hit = {i}
                break
            for k in (2, 3):  # "nodebeast" == "node" + "beast"
                if i + k <= len(tokens) and "".join(tokens[i:i + k]) == w:
                    hit = set(range(i, i + k))
                    break
            if hit:
                break
        if hit is None:
            return None
        used |= hit
    return used


def _hint_match(token: str, hint_words: set[str], hint_slugs: list[str]) -> bool:
    if token in hint_words:
        return True
    if len(token) >= 4 and any(token in h for h in hint_slugs):        # "shock" in "shockcannon"
        return True
    return any(len(h) >= 4 and h in token for h in hint_words)          # "lash" in "lashwhip"


class ImageLibrary:
    def __init__(self, folder: Path, aliases: dict):
        self.folder = folder
        self.aliases = aliases
        self.files: list[ImageFile] = []
        for p in sorted(folder.iterdir()) if folder.is_dir() else []:
            if p.suffix.lower() in IMAGE_EXTENSIONS and not p.stem.lower().startswith(OUTPUT_PREFIXES + ("dispo",)):
                self.files.append(parse_filename(p))
        self._cache: dict[Path, Image.Image] = {}
        self._scaled: dict[tuple, Image.Image] = {}

    def find(self, name: str, hints: list[str] | None = None) -> list[Path]:
        """Best matching image(s) for a unit. Several results are variants to mix.

        A file matches when every word of the unit name appears in the file name.
        Extra words in the file name (e.g. 'impaler' in spiky-monster-impaler.png)
        are compared with the wargear / model names in `hints`: +10 for every extra
        word that matches, -1 for every one that doesn't. Words behind a variant
        marker such as '-a' only count (-0.5) when some image matches the wargear,
        so plain variants (-a, -b, -c ...) are all returned and mixed.
        """
        if name in self.aliases:
            v = self.aliases[name]
            v = v if isinstance(v, list) else [v]
            return [self.folder / x for x in v if (self.folder / x).exists()]
        hints = hints or []
        hint_words = {w for h in hints for w in words(h) if len(w) >= 3}
        hint_slugs = [slug(h) for h in hints]
        nw = name_words(name)
        if not nw:
            return []
        attempts = [nw, ["".join(nw)]] if len(nw) > 1 else [nw]
        for attempt in attempts:
            cands = []  # (hits, unmatched words before a variant marker, unmatched words after it, path)
            for f in self.files:
                used = _match_name(attempt, f.tokens)
                if used is None:
                    continue
                hits = pre = post = 0
                for i, t in enumerate(f.tokens):
                    if i in used:
                        continue
                    if _hint_match(t, hint_words, hint_slugs):
                        hits += 1
                    elif f.variant_at is not None and i >= f.variant_at:
                        post += 1
                    else:
                        pre += 1
                cands.append((hits, pre, post, f.path))
            if cands:
                # Words behind a variant marker ("hormagaunt-c-leaping") only matter when some
                # image matches the wargear; otherwise all variants are mixed for variety.
                post_w = 0.5 if any(c[0] for c in cands) else 0
                scored = [(10 * h - pre - post_w * post, p) for h, pre, post, p in cands]
                best = max(s for s, _ in scored)
                return sorted(p for s, p in scored if s == best)
        # last resort: typos ("Termagnts")
        keys = {slug("".join(f.tokens)): f.path for f in self.files}
        hit = difflib.get_close_matches(slug("".join(nw)), keys.keys(), n=1, cutoff=0.82)
        return [keys[hit[0]]] if hit else []

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
    d.text((w / 2 - 3, height / 2 - 6), "?", fill=(110, 110, 120))
    return im


# --------------------------------------------------------------------------- #
# Dispositions
# --------------------------------------------------------------------------- #
def disposition_index(text: str | None) -> int | None:
    k = slug(re.sub(r"^force disposition:\s*", "", text or "", flags=re.I))
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
    result: dict[int, int] = dict(army.links)  # leaders written in the export ("Leading:", "+ 6x ...")
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

    def model_images(self, unit: Unit) -> list[Path | None]:
        """One image path per model. Model groups with their own wargear get their own best match."""
        result: list[Path | None] = []
        groups = unit.groups or [ModelGroup(unit.models, unit.name)]
        if sum(g.count for g in groups) < unit.models:  # e.g. unit-level count only
            groups = [ModelGroup(unit.models, unit.name)]
        for g in groups:
            hints = unit.wargear + [g.name] + g.wargear
            m = re.search(r"\s+with\s+(.+)$", unit.name, re.I)
            if m:
                hints.append(m.group(1))
            imgs = self.lib.find(unit.name, hints)
            if not imgs and slug(g.name) != slug(unit.name):
                imgs = self.lib.find(g.name, hints)
            picks = [imgs[i % len(imgs)] if imgs else None for i in range(g.count)]
            random.Random(unit.name + g.name).shuffle(picks)  # use every variant, in a mixed order
            result += picks
        if all(p is None for p in result) and unit.name not in self.missing:
            self.missing.append(unit.name)
        return result

    def height_of(self, unit: Unit, path: Path | None) -> int:
        """Images are expected to share one scale, so we keep their native size."""
        if path is not None:
            h = self.lib.load(path).height * self.scale
        else:  # rough guess from points per model
            h = 62 * max(1, unit.points / unit.models) ** 0.42 * self.scale
        return max(1, int(h * self.overrides.get(unit.name, 1.0)))

    def draw_group(self, squad: Unit, leaders: list[Unit], loose: bool = False) -> Image.Image:
        """Draw one unit (plus its leaders). loose=True spreads the models out (showcase layout)."""
        rnd = random.Random(squad.name)
        paths = self.model_images(squad)
        n = len(paths)
        heights = [self.height_of(squad, p) for p in paths]
        h = max(heights)
        widths = [(self.lib.load(p).width / self.lib.load(p).height * hh) if p else hh * 0.6
                  for p, hh in zip(paths, heights)]
        if loose:
            spacing = (sum(widths) / n) * (1.05 if n > 1 else 1)
            cols = n if n <= 3 else math.ceil(math.sqrt(n * 1.6))
            depth = h * 0.5
            jitter_x, jitter_y = spacing * 0.15, depth * 0.12
        else:
            spacing = (sum(widths) / n) * (0.55 if n > 1 else 1)
            cols = n if n <= 6 else max(5, math.ceil(math.sqrt(n * 2.2)))
            depth = h * 0.32
            jitter_x, jitter_y = 6, 4
        rows = math.ceil(n / cols)

        pieces = []  # (x centre, ground y, image)
        k = 0
        for r in range(rows):
            in_row = min(cols, n - r * cols)
            back = rows - 1 - r
            s = 1 - 0.07 * back
            darken = int((35 if loose else 70) * back / max(1, rows - 1)) if rows > 1 else 0
            ground = -back * depth
            shift = spacing / 2 if back % 2 else 0
            for c in range(in_row):
                x = (c - (in_row - 1) / 2) * spacing * s + shift + rnd.uniform(-jitter_x, jitter_x)
                p, hh = paths[k], heights[k]
                k += 1
                if p is not None:
                    im = self.lib.model(p, int(hh * s), rnd.random() < 0.4, darken)
                else:
                    im = placeholder(int(hh * s))
                pieces.append((x, ground + rnd.uniform(-jitter_y, jitter_y), im))

        # leaders stand in front of their unit; a leader unit can have several models
        front = []
        for ld in leaders:
            lps = [p for p in self.model_images(ld)] or [None]
            if all(p is None for p in lps):
                lps = [None]
            for lp in lps:
                lh = self.height_of(ld, lp)
                front.append(self.lib.model(lp, lh) if lp else placeholder(lh))
        if front:
            step = sum(im.width for im in front) / len(front) * (1.0 if loose else 0.75)
            for i, im in enumerate(front):
                x = (i - (len(front) - 1) / 2) * step
                pieces.append((x, depth * (0.7 if loose else 0.45) + (i % 2) * 6, im))

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


LAYOUTS = {"group": "group-photo", "showcase": "battle-ready", "ready": "battle-ready"}  # old / short names


def choose_hero(groups: list, center: str | None, seed) -> int:
    """Index of the group that goes in the middle: the one named by --center, else a random
    character (preferably one leading a unit)."""
    if center and center.startswith("#"):  # a unit id, from the menu
        uid = int(center[1:])
        for i, (sq, ls) in enumerate(groups):
            if any(u.id == uid for u in [sq] + ls):
                return i
    elif center:
        key = slug(center)
        for i, (sq, ls) in enumerate(groups):
            if any(slug(u.name).startswith(key) or key in slug(u.name) for u in [sq] + ls):
                return i
        print(f"Note: no unit called '{center}' found, picking a random character instead.")
    rnd = random.Random(seed)
    led = [i for i, (sq, ls) in enumerate(groups) if ls]
    chars = [i for i, (sq, _) in enumerate(groups) if sq.character or sq.warlord]
    pool = led or chars or list(range(len(groups)))
    return rnd.choice(pool)


def center_options(army: ArmyList, leaders: dict[int, int]) -> list[tuple[str, str]]:
    """(label, "#unit id") for every character and attached unit of the list."""
    by_id = {u.id: u for u in army.units}
    opts, seen = [], set()
    for c, t in sorted(leaders.items()):
        label = f"{by_id[c].name} + {by_id[t].name}" + (" (Warlord)" if by_id[c].warlord else "")
        opts.append((label, f"#{c}"))
        seen.add(c)
    for u in army.units:
        if (u.character or u.warlord) and u.id not in seen and u.id not in leaders.values():
            opts.append((u.name + (" (Warlord)" if u.warlord else ""), f"#{u.id}"))
    # tell identical entries apart: "Broodlord + Genestealers (2)"
    labels = [l for l, _ in opts]
    out = []
    for i, (l, v) in enumerate(opts):
        if labels.count(l) > 1:
            l = f"{l} ({labels[:i + 1].count(l)})"
        out.append((l, v))
    return out


def ask_center(army: ArmyList, leaders: dict[int, int]) -> str | None:
    opts = center_options(army, leaders)
    if not opts or not sys.stdin.isatty():
        return None
    print("\nWho stands in the middle?")
    for i, (label, _) in enumerate(opts, 1):
        print(f"  {i}) {label}")
    try:
        answer = input("Number (Enter = random): ").strip()
    except EOFError:
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(opts):
        return opts[int(answer) - 1][1]
    return None


def _group_rows(pictures: list[Image.Image], overlap: int) -> list[list[Image.Image]]:
    """Packed group photo: tall units in the back, small ones in front, centre-out."""
    pictures = sorted(pictures, key=lambda b: b.height, reverse=True)
    area = sum(b.width * b.height for b in pictures)
    max_w = max(max(b.width for b in pictures) * 1.4, math.sqrt(area) * 1.7)
    gap = -overlap
    rows, cur, w = [], [], 0
    for b in pictures:
        if cur and w + gap + b.width > max_w:
            rows.append(cur)
            cur, w = [], 0
        cur.append(b)
        w += (gap if w else 0) + b.width
    if cur:
        rows.append(cur)
    return [_center_out(r) for r in rows]


def _edges_in(items: list) -> list:
    """Largest items to the outer edges: [1, 2, 3, 4, 5] -> [1, 3, 5, 4, 2]."""
    left, right = [], []
    for i, it in enumerate(items):
        (left if i % 2 == 0 else right).append(it)
    return left + list(reversed(right))


def _battle_ready(pictures: list[Image.Image], hero: int, cfg: dict) -> Image.Image:
    """Box-art style, as if the camera looks down at the table from the front.

    The hero unit stands alone in the front centre. All other units stand on curved rings
    around it: the further a unit is to the side, the further back it stands, so the rings
    bend upwards like a U. Small units are close to the front, big ones on the outer rings,
    and the tallest one may stand right behind the hero. Everything further back is drawn
    smaller and higher up (perspective).
    """
    hero_pic = pictures[hero]
    H = float(max(hero_pic.height, 1))
    others = [p for i, p in enumerate(pictures) if i != hero]
    widths = sorted(p.width for p in pictures)
    gap = widths[len(widths) // 2] * 0.25
    corridor = hero_pic.width + 2 * gap
    persp = float(cfg.get("perspective", 0.18))   # how much smaller things get further back
    tilt = float(cfg.get("tilt", 0.65))           # how much higher things get further back
    curve = float(cfg.get("curve", 0.15))         # how strongly the rings bend backwards at the sides

    tallest = max([p.height for p in others] or [0])
    big = sorted([p for p in others if p.height >= 0.6 * tallest], key=lambda b: b.height)
    small = sorted([p for p in others if p.height < 0.6 * tallest], key=lambda b: b.height)
    center_back = big.pop() if big and len(others) > 2 else None

    area = sum(p.width * p.height for p in others) or 1
    limit = max(math.sqrt(area) * 1.1, corridor * 1.5)

    def scale(z):
        return 1 / (1 + persp * z / H)

    placed = []  # (x world, z world, picture)
    z_ring = 0.3 * H

    def fill(items):
        nonlocal z_ring
        ring = 0
        i = 0
        while i < len(items):
            ext = {-1: corridor / 2, 1: corridor / 2}
            lim = limit * (1 + 0.35 * ring)
            ring_items = []
            while i < len(items):
                b = items[i]
                side = -1 if ext[-1] <= ext[1] else 1
                if ring_items and ext[side] + b.width > lim:
                    break
                xc = ext[side] + b.width / 2
                ext[side] += b.width + gap
                ring_items.append((side * xc, b))
                i += 1
            for x, b in ring_items:
                z = z_ring + curve * (abs(x) / H) ** 2 * H
                placed.append((x, z, b))
            z_ring += max(0.5 * H, 0.65 * max(b.height for _, b in ring_items))
            ring += 1

    fill(small)
    fill(big)

    def project(x, z, b, cx, base_y):
        f = scale(z)
        w, h = max(1, int(b.width * f)), max(1, int(b.height * f))
        sx = cx + x * f - w / 2
        gy = base_y - tilt * z * f
        return sx, gy - h, w, h

    if center_back is not None:
        # as close as possible, but far enough back that the hero hides at most a fifth of it
        # (measured on the visible pixels, not on the transparent padding around them)
        hb = hero_pic.getchannel("A").getbbox() or (0, 0, hero_pic.width, hero_pic.height)
        cb = center_back.getchannel("A").getbbox() or (0, 0, center_back.width, center_back.height)
        hero_top = -hero_pic.height + hb[1]
        z = 0.3 * H
        for _ in range(60):
            f = scale(z)
            _, top_c, _, _ = project(0, z, center_back, 0, 0)
            vis_top, vis_bottom = top_c + cb[1] * f, top_c + cb[3] * f
            if vis_bottom - hero_top <= 0.2 * (vis_bottom - vis_top):
                break
            z += 0.1 * H
        placed.append((0.0, z, center_back))
    placed.append((0.0, 0.0, hero_pic))
    placed = _resolve_occlusion(placed, project, H, float(cfg.get("max_hidden", 0.01)))

    boxes = [project(x, z, b, 0, 0) for x, z, b in placed]
    min_x = min(bx for bx, _, _, _ in boxes)
    max_x = max(bx + w for bx, _, w, _ in boxes)
    min_y = min(by for _, by, _, _ in boxes)
    max_y = max(by + h for _, by, _, h in boxes)
    half = max(-min_x, max_x)  # keep the hero exactly in the middle
    M = int(cfg["margin"])
    W = int(2 * half) + 2 * M
    Hc = int(max_y - min_y) + 2 * M
    photo = Image.new("RGBA", (W, Hc), _parse_color(cfg["background"]))
    cx, base_y = W / 2, M - min_y
    for (x, z, b) in sorted(placed, key=lambda t: -t[1]):  # far away first
        sx, sy, w, h = project(x, z, b, cx, base_y)
        img = b if (w, h) == b.size else b.resize((w, h), Image.LANCZOS)
        photo.alpha_composite(img, (int(sx), int(sy)))
    return photo


def _resolve_occlusion(placed: list, project, H: float, max_hidden: float) -> list:
    """Push units back and a little towards the middle (which also makes them smaller and higher
    up) until the units in front of them hide at most `max_hidden` of their visible pixels.
    The hero (z = 0) never moves."""
    DS = 8  # work on 1/8 size masks, that's precise enough and fast
    masks = {}

    def small_mask(b):
        if id(b) not in masks:
            masks[id(b)] = b.getchannel("A").point(lambda a: 255 if a > 60 else 0).resize(
                (max(1, b.width // DS), max(1, b.height // DS)), Image.NEAREST)
        return masks[id(b)]

    def footprint(x, z, b):
        sx, sy, w, h = project(x, z, b, 0, 0)
        m = small_mask(b).resize((max(1, int(w / DS)), max(1, int(h / DS))), Image.NEAREST)
        return int(sx // DS), int(sy // DS), m

    items = [list(t) for t in placed]
    hero = placed[-1][2]

    def hidden_share(it, x, z):
        bx, by, bm = footprint(x, z, it[2])
        cover = Image.new("L", bm.size, 0)
        for o in items:
            if o is not it and o[1] < z:
                ox, oy, om = footprint(*o)
                cover.paste(255, (ox - bx, oy - by), om)
        visible = bm.histogram()[255] or 1
        return Image.composite(cover, Image.new("L", bm.size, 0), bm).histogram()[255] / visible

    for _ in range(6):  # a few passes: pushing one unit back can affect the ones behind it
        changed = False
        for it in sorted(items, key=lambda t: t[1]):
            if it[2] is hero:
                continue  # the hero stays where it is
            for _step in range(60):
                if hidden_share(it, it[0], it[1]) <= max_hidden:
                    break
                # step back, and preferably a little towards the middle (the army forms a circle);
                # sideways if that frees the unit better
                z = it[1] + 0.08 * H
                options = [(it[0] * 0.97, z), (it[0], z), (it[0] * 1.03 + (0.03 * H if it[0] >= 0 else -0.03 * H), z)]
                scores = [hidden_share(it, x, zz) for x, zz in options]
                best = min(range(3), key=lambda k: (round(scores[k], 3), k))
                it[0], it[1] = options[best]
                changed = True
        if not changed:
            break
    return [tuple(t) for t in items]


def _compose(rows: list[list[Image.Image]], gap: int, overlap_factor: float, justify_back: bool,
             cfg: dict, anchor: dict[int, int] | None = None) -> Image.Image:
    """Place rows from back to front; every row stands a bit lower so it overlaps the one behind.
    anchor = {row index: item index} puts that item exactly in the middle of the picture."""
    anchor = anchor or {}
    placed, ground = [], 0
    for i, row in enumerate(rows):
        rw = sum(b.width for b in row) + gap * (len(row) - 1)
        if i in anchor:  # room needed on both sides of the centred item
            a = anchor[i]
            left = sum(b.width + gap for b in row[:a]) + row[a].width / 2
            right = sum(b.width + gap for b in row[a + 1:]) + row[a].width / 2
            rw = 2 * max(left, right)
        if i:
            ground += max(60, int(max(b.height for b in row) * overlap_factor))
        placed.append((row, ground, rw))
    full = max(rw for _, _, rw in placed)
    top = min(g - max(b.height for b in row) for row, g, _ in placed)
    bottom = max(g for _, g, _ in placed)
    M = int(cfg["margin"])
    W = int(full) + 2 * M
    H = int(bottom - top) + 2 * M
    photo = Image.new("RGBA", (W, H), _parse_color(cfg["background"]))
    for i, (row, g, rw) in enumerate(placed):
        step = gap
        if i == 0 and justify_back and len(row) > 1 and len(placed) > 1:
            step = (full - sum(b.width for b in row)) / (len(row) - 1)  # spread the back row to the corners
            rw = full
        x = (W - rw) / 2
        if i in anchor:
            a = anchor[i]
            x = W / 2 - row[a].width / 2 - sum(b.width + gap for b in row[:a])
        base = g - top + M
        for b in row:
            photo.alpha_composite(b, (int(x), int(base - b.height)))
            x += b.width + step
    return photo


def render(army: ArmyList, lib: ImageLibrary, cfg: dict, leaders: dict[int, int],
           scale_overrides: dict) -> tuple[Image.Image, list[str]]:
    r = Renderer(lib, cfg, scale_overrides)
    by_id = {u.id: u for u in army.units}

    def has_image(u: Unit) -> bool:
        return any(p is not None for p in r.model_images(u))

    groups = []
    for u in army.units:
        if u.id in leaders:
            continue
        led_by = [by_id[c] for c, t in leaders.items() if t == u.id]
        if not cfg["placeholders"]:
            led_by = [l for l in led_by if has_image(l)]
            if not has_image(u):
                if not led_by:
                    continue
                u, led_by = led_by[0], led_by[1:]
        groups.append((u, led_by))

    heights = [lib.load(p).height for sq, ls in groups for un in [sq] + ls for p in r.model_images(un) if p]
    r.scale = min(1.0, cfg["max_model_height"] / max(heights)) if heights else 1.0
    if not groups:
        raise SystemExit("No images found for any unit. Check the --images folder and file names.")

    if LAYOUTS.get(cfg["layout"], cfg["layout"]) == "battle-ready":
        hero = choose_hero(groups, cfg.get("center"), cfg.get("seed"))
        pictures = [r.draw_group(sq, ls, loose=True) for sq, ls in groups]
        photo = _battle_ready(pictures, hero, cfg)
    else:
        pictures = [r.draw_group(sq, ls) for sq, ls in groups]
        rows = _group_rows(pictures, int(cfg["overlap"]))
        photo = _compose(rows, -int(cfg["overlap"]), 0.35, False, cfg)
    return photo, list(dict.fromkeys(r.missing))


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


def looks_like_list(text: str) -> bool:
    return bool(text) and bool(parse_list(text).units)


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
        root = base / "images"
        if root.is_dir():
            subs = [d for d in root.iterdir() if d.is_dir()]
            return subs[0] if len(subs) == 1 else root
    return here


def load_config(folder: Path) -> dict:
    p = folder / CONFIG_NAME
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


FORMAT_NAMES = {"gw": "GW", "compact": "compact (WTC)", "simple": "simple", "bracket": "minimal",
                "roster": "roster (BattleScribe style)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="army-photo",
                                 description="Turn a New Recruit army list into a group photo of your models.")
    ap.add_argument("list", nargs="*", help="text file with the list (default: clipboard); "
                                            "with --board a second file is the opponent")
    ap.add_argument("-o", "--output", help="output file (default: army_photo_<list name>.png)")
    ap.add_argument("-i", "--images", help="folder with model images (default: images/<faction>)")
    ap.add_argument("-l", "--leader", action="append", default=[], metavar="CHARACTER=UNIT",
                    help='attach a leader, e.g. "Boss Monster=Little Monsters" (repeatable)')
    ap.add_argument("-m", "--models", action="append", default=[], metavar="UNIT=COUNT",
                    help='set the model count of a unit, e.g. "Little Monsters=20" (repeatable)')
    ap.add_argument("--no-questions", action="store_true", help="never ask which unit a character leads")
    ap.add_argument("--background", help='"#ffffff", "#000000", "transparent", ...')
    ap.add_argument("--transparent", action="store_true", help="shortcut for --background transparent")
    ap.add_argument("--max-height", type=int, help="height of the tallest model in pixels")
    ap.add_argument("--placeholders", action="store_true", help='show "?" for models without an image')
    ap.add_argument("--layout", choices=["group-photo", "battle-ready"],
                    help="group-photo: packed like a team photo (default); "
                         "battle-ready: spread out like box art, a hero in the middle")
    ap.add_argument("--battle-ready", action="store_true", help="shortcut for --layout battle-ready")
    ap.add_argument("--group-photo", action="store_true", help="shortcut for --layout group-photo")
    ap.add_argument("--center", metavar="UNIT", help='battle-ready: unit or character to put in the middle; '
                                                      '"ask" shows a menu (default: a random character)')
    ap.add_argument("--seed", type=int, help="battle-ready: fixed random seed, to get the same pick again")
    ap.add_argument("--no-disposition", action="store_true", help="do not add the disposition icon")
    ap.add_argument("--extract-dispositions", metavar="CARD",
                    help="cut the 5 icons out of a disposition card into <images>/dispositions/ and exit")
    ap.add_argument("--no-open", action="store_true", help="do not open the result afterwards")
    ap.add_argument("--board", action="store_true",
                    help="deployment board: models as tokens with their real base size in the deployment zones")
    ap.add_argument("--map", help='board: deployment map, e.g. "crucible-of-battle"; "ask" shows a menu; '
                                  '"auto" detects it from --terrain')
    ap.add_argument("--board-style", choices=["tokens", "models", "ask"], default="tokens",
                    help="board: round tokens with the model inside (default) or models standing on their bases")
    ap.add_argument("--terrain", metavar="LAYOUT", help='board: terrain layout: "ask" (menu), "random", '
                    '"none" (default), a number like "43" from images/layouts, or any image file')
    ap.add_argument("--no-terrain", action="store_true", help="board: plain battlefield without terrain layout")
    ap.add_argument("--bases", metavar="JSON", help="board: extra base size file (besides <images>/bases.json)")
    ap.add_argument("--enemy-images", metavar="DIR", help="board: image folder of the second army")
    ap.add_argument("--ppi", type=float, default=30, help="board: pixels per inch (default 30)")
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

    if args.board:
        import board
        # image files given as arguments (e.g. dropped onto board.bat) are the terrain layout
        images = [f for f in args.list if Path(f).suffix.lower() in IMAGE_EXTENSIONS]
        if images and not args.terrain:
            args.terrain = images[0]
        lists = [f for f in args.list if f not in images]
        texts = [Path(f).read_text(encoding="utf-8") for f in lists[:2]]
        if not texts:
            clip = read_clipboard()
            if looks_like_list(clip):
                print("Read army list from clipboard.")
                texts = [clip]
            else:
                print("No army list in the clipboard. Paste it here, then press "
                      "Ctrl+Z and Enter (Windows) or Ctrl+D (macOS/Linux):")
                texts = [sys.stdin.read()]
            # second army: copy the opponent's list, then press Enter
            if sys.stdin.isatty() and clip and looks_like_list(clip):
                try:
                    input("\nOpponent: copy the second list in New Recruit and press Enter "
                          "(or just press Enter to deploy only your army): ")
                except EOFError:
                    pass
                clip2 = read_clipboard()
                if clip2 and clip2.strip() != clip.strip() and looks_like_list(clip2):
                    print("Read the opponent's list from clipboard.")
                    texts.append(clip2)
        return board.run(texts, args)

    if args.list:
        text = Path(args.list[0]).read_text(encoding="utf-8")
    else:
        text = read_clipboard()
        if not looks_like_list(text):
            print("No army list in the clipboard. Paste it here, then press "
                  "Ctrl+Z and Enter (Windows) or Ctrl+D (macOS/Linux):")
            text = sys.stdin.read()
        else:
            print("Read army list from clipboard.")
    army = parse_list(text)
    if not army.units:
        print("No units found - is this a New Recruit text export?")
        return 1
    print(f"List format: {FORMAT_NAMES.get(army.format, army.format)} - {len(army.units)} units")

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
    if args.layout:
        cfg["layout"] = args.layout
    if args.battle_ready:
        cfg["layout"] = "battle-ready"
    if args.group_photo:
        cfg["layout"] = "group-photo"
    cfg["layout"] = LAYOUTS.get(cfg["layout"], cfg["layout"])
    if args.center:
        cfg["center"] = args.center
    if args.seed is not None:
        cfg["seed"] = args.seed

    counts = {slug(k): int(v) for k, v in conf.get("models", {}).items()}
    counts.update({slug(a.split("=", 1)[0]): int(a.split("=", 1)[1]) for a in args.models if "=" in a})
    for u in army.units:
        if slug(u.name) in counts:
            u.models, u.groups = counts[slug(u.name)], []
    if not army.has_model_counts and not counts:
        print("Note: this list format has no model counts, every unit is shown with one model.\n"
              '      Use the GW or roster export, or set counts with -m "Unit=20" / "models" in army.json.')

    presets = dict(conf.get("leaders", {}))
    presets.update(dict(a.split("=", 1) for a in args.leader if "=" in a))
    leaders = resolve_leaders(army, presets, ask=not args.no_questions)

    if cfg["layout"] == "battle-ready" and str(cfg.get("center") or "").lower() == "ask":
        cfg["center"] = ask_center(army, leaders)

    lib = ImageLibrary(folder, conf.get("images", {}))
    print(f"Using images from: {folder}")
    photo, missing = render(army, lib, cfg, leaders, conf.get("scale", {}))

    if not args.no_disposition and army.disposition:
        icon = find_disposition_icon(folder, army.disposition)
        if icon is not None:
            paste_disposition(photo, icon, cfg)

    suffix = "_battle_ready" if cfg["layout"] == "battle-ready" else ""
    target = Path(args.output) if args.output else \
        folder / f"army_photo_{slug(army.title or army.faction) or 'army'}{suffix}.png"
    out = photo if cfg["background"] == "transparent" else photo.convert("RGB")
    target = save(out, target)
    print(f"\nSaved: {target}")
    if missing:
        print("No image found (left out):", ", ".join(missing))
        print(f"Tip: name the file after the unit (e.g. '{'-'.join(name_words(missing[0]))}.png') "
              f"or add it to {CONFIG_NAME}.")
    if not args.no_open and sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    sys.exit(main())
