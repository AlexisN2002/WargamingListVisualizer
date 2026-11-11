from pathlib import Path

from PIL import Image

import army_photo as ap

ROOT = Path(__file__).resolve().parent.parent

ATTACHED_LIST = """Swarm2k (2,000 Points)

Monster Army
Endless Tide (3 Detachment Points)
Priority Assets
Strike Force (2,000 Points)

ATTACHED UNITS

Attached unit 1

Boss Monster with Big Club (100 Points)
  • Attached as: Leader (Character)
  • 1x Big club
  • Enhancements: Chitin Crown

Little Monsters (70 Points)
  • Attached as: Bodyguard (Battleline)
  • 10x Little Monsters
     ◦ 10x Claws

CHARACTERS

The Big Monster (210 Points)
  • Warlord
  • 1x Crushing claws

OTHER DATASHEETS

Spitting Monsters (100 Points)
  • 3x Spitting Monster
     ◦ 3x Spindly legs
     ◦ 3x Acid glands

Flying Monster (60 Points)
  • 1x Diving talons

Exported with New Recruit v37.21, Data Version: v3
"""


def test_header():
    army = ap.parse_list(ATTACHED_LIST)
    assert army.title == "Swarm2k"
    assert army.points == "2,000"
    assert army.faction == "Monster Army"
    assert army.detachment == "Endless Tide"
    assert army.disposition == "Priority Assets"


def test_units_and_model_counts():
    army = ap.parse_list(ATTACHED_LIST)
    counts = {u.name: u.models for u in army.units}
    assert counts == {"Boss Monster with Big Club": 1, "Little Monsters": 10, "The Big Monster": 1,
                      "Spitting Monsters": 3, "Flying Monster": 1}
    big = next(u for u in army.units if u.name == "The Big Monster")
    assert big.warlord and big.character
    boss = army.units[0]
    assert boss.enhancement == "Chitin Crown"


def test_attached_units_are_resolved_without_questions():
    army = ap.parse_list(ATTACHED_LIST)
    leaders = ap.resolve_leaders(army, {}, ask=True)
    assert leaders == {0: 1}


def test_leader_presets():
    text = (ROOT / "examples" / "demo_list.txt").read_text(encoding="utf-8")
    army = ap.parse_list(text.replace("ATTACHED UNITS", "BATTLELINE").replace("Attached unit 1", ""))
    army.has_attachments = False
    for u in army.units:
        u.attached_role, u.attached_group = "", None
    army.units[0].character = True
    leaders = ap.resolve_leaders(army, {"Boss Monster": "Little Monsters"}, ask=False)
    assert leaders == {0: 1}


def test_filename_parsing():
    f = ap.parse_filename(Path("little-monster-2023-a.webp"))
    assert f.tokens == ["little", "monster"] and f.variant_at == 2
    f = ap.parse_filename(Path("spiky-monster-b-big-spikes.png"))
    assert f.tokens == ["spiky", "monster", "big", "spike"] and f.variant_at == 2
    assert ap.name_words("Boss Monster with Big Club") == ["boss", "monster"]
    assert ap.name_words("The Big Monster") == ["big", "monster"]
    assert ap.name_words("Little Monsters") == ["little", "monster"]


def test_disposition_index():
    assert ap.disposition_index("Priority Assets") == 3
    assert ap.disposition_index("priority-asset") == 3
    assert ap.disposition_index("Strike Force") is None


def test_demo_render(tmp_path):
    out = tmp_path / "demo.png"
    rc = ap.main([str(ROOT / "examples" / "demo_list.txt"), "-i", str(ROOT / "examples" / "demo_images"),
                  "-o", str(out), "--no-open", "--no-questions"])
    assert rc == 0
    im = Image.open(out)
    assert im.width > 500 and im.height > 300
    assert im.getpixel((2, 2))[:3] == (255, 255, 255)


def test_list_from_clipboard(tmp_path, monkeypatch):
    text = (ROOT / "examples" / "demo_list.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(ap, "read_clipboard", lambda: text)
    out = tmp_path / "clip.png"
    rc = ap.main(["-i", str(ROOT / "examples" / "demo_images"), "-o", str(out), "--no-open", "--no-questions"])
    assert rc == 0 and out.exists()


# --------------------------------------------------------------------------- #
# Other New Recruit export formats
# --------------------------------------------------------------------------- #
COMPACT = """Monster Party (1,000 Points)

Monster Army
Endless Tide (3 Detachment Points)
Purge the Foe
Incursion (1,000 Points)

Char1: 1x Smart Monster (130 pts): Warlord, Psychic lash
Enhancement: Big Brain (+20 pts)

1x Big Monster (380 pts): Crushing claws
10x Little Monsters (90 pts): 10x Claws
1x Spiky Monster (150 pts): Spike volley

Created with newrecruit.eu v37.21
"""

SIMPLE = """Monsters - Monster Army - Endless Tide
Purge the Foe

Smart Monster (130pts): Warlord
Big Monster (380pts)
Spiky Monster (150pts): Spike volley
"""

ROSTER = """Monsters - Monster Army - Monster Party - [1000 pts]

# ++ Army Roster ++ [1000 pts, 3 Detachment Points]
## Configuration
Battle Size: Incursion (1000 Point limit)
Detachment [3 Detachment Points]: Endless Tide [3 Detachment Points]
Force Disposition: Purge the Foe

## Character [130 pts]
Smart Monster [130 pts]: Warlord, Big Brain [20 pts], Psychic lash

## Battleline [90 pts]
Little Monsters [90 pts]:
• 8x Little Monster: Claws
• 2x Little Monster: Spit glands

## Monster [380 pts]
Big Monster [380 pts]: Crushing claws

Created with newrecruit.eu v37.21
"""

MINIMAL = """Monsters - Monster Army - Monster Party - [1000 pts]

Smart Monster [130 pts]

Little Monsters [90 pts]:
• 10x Little Monster
Big Monster [380 pts]
"""


def test_detect_formats():
    assert ap.parse_list(ATTACHED_LIST).format == "gw"
    assert ap.parse_list(COMPACT).format == "compact"
    assert ap.parse_list(SIMPLE).format == "simple"
    assert ap.parse_list(ROSTER).format == "roster"
    assert ap.parse_list(MINIMAL).format == "bracket"


def test_compact_format():
    army = ap.parse_list(COMPACT)
    assert (army.title, army.faction, army.detachment, army.disposition) == \
        ("Monster Party", "Monster Army", "Endless Tide", "Purge the Foe")
    names = {u.name: u for u in army.units}
    assert list(names) == ["Smart Monster", "Big Monster", "Little Monsters", "Spiky Monster"]
    assert names["Smart Monster"].warlord and names["Smart Monster"].character
    assert names["Smart Monster"].enhancement == "Big Brain"
    assert names["Little Monsters"].models == 10
    assert names["Spiky Monster"].wargear == ["Spike volley"]


def test_simple_format():
    army = ap.parse_list(SIMPLE)
    assert (army.faction, army.detachment, army.disposition) == ("Monster Army", "Endless Tide", "Purge the Foe")
    assert [u.name for u in army.units] == ["Smart Monster", "Big Monster", "Spiky Monster"]
    assert army.units[0].warlord
    assert not army.has_model_counts


def test_roster_format():
    army = ap.parse_list(ROSTER)
    assert (army.title, army.points, army.faction, army.detachment, army.disposition) == \
        ("Monster Party", "1000", "Monster Army", "Endless Tide", "Purge the Foe")
    names = {u.name: u for u in army.units}
    assert names["Smart Monster"].character and names["Smart Monster"].warlord
    little = names["Little Monsters"]
    assert little.models == 10
    assert [(g.count, g.wargear) for g in little.groups] == [(8, ["Claws"]), (2, ["Spit glands"])]


def test_minimal_format():
    army = ap.parse_list(MINIMAL)
    assert army.title == "Monster Party" and army.faction == "Monster Army"
    assert [(u.name, u.models) for u in army.units] == [("Smart Monster", 1), ("Little Monsters", 10),
                                                        ("Big Monster", 1)]


# --------------------------------------------------------------------------- #
# Image matching
# --------------------------------------------------------------------------- #
def _library(tmp_path, names):
    for n in names:
        Image.new("RGBA", (10, 20), (200, 0, 0, 255)).save(tmp_path / n)
    return ap.ImageLibrary(tmp_path, {})


def _names(paths):
    return [p.name for p in paths]


def test_wargear_picks_matching_image(tmp_path):
    lib = _library(tmp_path, ["spiky-monster-impaler.png", "spiky-monster-shock.png", "spiky-monster-boss.png"])
    assert _names(lib.find("Spiky Monsters", ["Impaler cannon"])) == ["spiky-monster-impaler.png"]
    assert _names(lib.find("Spiky Monsters", ["Shockcannon"])) == ["spiky-monster-shock.png"]
    # no useful wargear -> mix every variant
    assert len(lib.find("Spiky Monsters", ["Claws"])) == 3


def test_variants_are_all_used(tmp_path):
    lib = _library(tmp_path, ["little-monster-a.png", "little-monster-b.png", "little-monster-c-jumping.png",
                              "little-monster-2023-d.png"])
    assert len(lib.find("Little Monsters", ["Claws"])) == 4


def test_plain_image_preferred_over_other_kits(tmp_path):
    lib = _library(tmp_path, ["big-monster-a.png", "big-monster-old-edition.png", "big-monster-wings.png",
                              "winged-big-monster-x.png", "little-monster.png"])
    assert _names(lib.find("Big Monster")) == ["big-monster-a.png"]
    assert "big-monster-wings.png" in _names(lib.find("Winged Big Monster"))
    assert _names(lib.find("Little Monsters")) == ["little-monster.png"]
    assert lib.find("Medium Monster") == []


def test_model_groups_get_their_own_images(tmp_path):
    lib = _library(tmp_path, ["little-monster-claws.png", "little-monster-spit.png"])
    army = ap.parse_list(ROSTER)
    little = next(u for u in army.units if u.name == "Little Monsters")
    r = ap.Renderer(lib, dict(ap.DEFAULTS), {})
    picks = _names(r.model_images(little))
    assert picks.count("little-monster-claws.png") == 8
    assert picks.count("little-monster-spit.png") == 2


def test_all_formats_render(tmp_path):
    for i, text in enumerate([COMPACT, SIMPLE, ROSTER, MINIMAL]):
        f = tmp_path / f"list{i}.txt"
        f.write_text(text, encoding="utf-8")
        out = tmp_path / f"out{i}.png"
        rc = ap.main([str(f), "-i", str(ROOT / "examples" / "demo_images"), "-o", str(out),
                      "--no-open", "--no-questions"])
        assert rc == 0 and out.exists()


def test_simple_format_attached_unit():
    text = """Monsters - Monster Army - Endless Tide
Disruption

Smart Monster (130pts): Big Brain
+ 6x Little Monsters (190pts)

Big Monster (215pts): Warlord
"""
    army = ap.parse_list(text)
    assert army.disposition == "Disruption"
    assert [(u.name, u.models) for u in army.units] == [("Smart Monster", 1), ("Little Monsters", 6),
                                                        ("Big Monster", 1)]
    assert ap.resolve_leaders(army, {}, ask=True) == {0: 1}


def test_bracket_format_leading_lines():
    text = """Monsters - Monster Army - Monster Party - [1000 pts]

Big Monster [215 pts]
Smart Monster [130 pts]:
  • Leading: Little Monsters

Little Monsters [190 pts]:
• 5x Little Monster
  • Leader: Smart Monster
"""
    army = ap.parse_list(text)
    little = next(u for u in army.units if u.name == "Little Monsters")
    assert little.models == 5
    assert ap.resolve_leaders(army, {}, ask=True) == {1: 2}


# --------------------------------------------------------------------------- #
# Layouts
# --------------------------------------------------------------------------- #
def test_choose_hero():
    army = ap.parse_list((ROOT / "examples" / "demo_list.txt").read_text(encoding="utf-8"))
    by = {u.name: u for u in army.units}
    groups = [(by["Little Monsters"], [by["Boss Monster"]]), (by["Big Monster"], []), (by["Smart Monster"], [])]
    assert ap.choose_hero(groups, "Boss", None) == 0
    assert ap.choose_hero(groups, "Big Monster", None) == 1
    assert ap.choose_hero(groups, None, 1) == 0  # random pick prefers a character leading a unit


def test_battle_ready_layout(tmp_path):
    for layout in (["--battle-ready", "--center", "Smart Monster"], ["--battle-ready"], ["--layout", "group-photo"]):
        out = tmp_path / "x.png"
        rc = ap.main([str(ROOT / "examples" / "demo_list.txt"), "-i", str(ROOT / "examples" / "demo_images"),
                      "-o", str(out), "--no-open", "--no-questions"] + layout)
        assert rc == 0 and out.exists()


def test_center_options():
    army = ap.parse_list((ROOT / "examples" / "demo_list.txt").read_text(encoding="utf-8"))
    opts = ap.center_options(army, ap.resolve_leaders(army, {}, ask=False))
    assert [l for l, _ in opts] == ["Boss Monster + Little Monsters", "Smart Monster (Warlord)"]
    by = {u.name: u for u in army.units}
    groups = [(by["Little Monsters"], [by["Boss Monster"]]), (by["Smart Monster"], [])]
    assert ap.choose_hero(groups, opts[1][1], None) == 1


TOURNAMENT = """Monster Vanguard (1,000 Points)

Monster Army
Endless Tide (2 Detachment Points)
Reconnaissance
Incursion (1,000 Points)

Char1: 1x Boss Monster (80 pts): Big club
Leading Little Monsters[1]
Char2: 1x Boss Monster (80 pts): Big club
Leading Little Monsters[2]
Char3: 5x Flying Monsters (175 pts)
• 4x Flying Monster
    3 with Claws
    1 with Claws, Spit glands
• 1x Flying Monster Prime: Warlord, Big claws
      Enhancement: Stalker (+10 pts)
  Leading Spitting Monsters

10x Little Monsters (140 pts): 10 with Claws
  Attached to Boss Monster[1]
10x Little Monsters (140 pts): 10 with Claws
  Attached to Boss Monster[2]
1x Big Monster (60 pts): Crushing claws
5x Spitting Monsters (125 pts): 5 with Acid glands
  Attached to Flying Monsters

Created with newrecruit.eu v37.25
"""


def test_compact_tournament_format():
    army = ap.parse_list(TOURNAMENT)
    assert army.format == "compact" and army.disposition == "Reconnaissance"
    by_id = {u.id: u for u in army.units}
    flying = by_id[2]
    assert flying.models == 5 and flying.warlord and flying.enhancement == "Stalker"
    assert [(g.count, g.wargear) for g in flying.groups] == [
        (3, ["Claws"]), (1, ["Claws", "Spit glands"]), (1, ["Big claws"])]
    assert by_id[3].wargear == ["Claws"]
    # every leader goes to the right unit, without asking
    assert ap.resolve_leaders(army, {}, ask=True) == {0: 3, 1: 4, 2: 6}
    labels = [l for l, _ in ap.center_options(army, ap.resolve_leaders(army, {}, ask=False))]
    assert labels == ["Boss Monster + Little Monsters (1)", "Boss Monster + Little Monsters (2)",
                      "Flying Monsters + Spitting Monsters (Warlord)"]


def test_compact_partial_wargear_lines_keep_all_models():
    text = """Squad Test (500 Points)

Robot Legion
Steel Vanguard (3 Detachment Points)
Purge the Foe
Incursion (1,000 Points)

5x Tin Soldiers (95 pts)
• 4x Tin Soldier
    1 with Banner
• 1x Sergeant Bot: Glow blade
10x Shield Bots (170 pts)
• 9x Shield Bot
    5 with Blaster
    1 with Banner, Long gun
• 1x Sergeant Bot: Glow blade
"""
    army = ap.parse_list(text)
    tin, shield = army.units
    assert tin.models == 5 and shield.models == 10
    assert sorted((g.count, tuple(g.wargear)) for g in tin.groups) == [(1, ()), (1, ("Banner",)), (1, ("Glow blade",)), (3, ())] or \
        sum(g.count for g in tin.groups) == 5
    assert sum(g.count for g in shield.groups) == 10
