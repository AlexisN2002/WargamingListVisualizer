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


def test_base_key_and_candidates():
    assert ap.base_key("little-monster-2023-a.webp") == "littlemonster"
    assert ap.base_key("spiky-monster-b.webp") == "spikymonster"
    assert "bossmonster" in ap.name_candidates("Boss Monster with Big Club")
    assert "bigmonster" in ap.name_candidates("The Big Monster")
    assert "littlemonster" in ap.name_candidates("Little Monsters")


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
