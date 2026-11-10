from pathlib import Path

from PIL import Image

import army_photo as ap

ROOT = Path(__file__).resolve().parent.parent

ATTACHED_LIST = """Assim2k (2,000 Points)

Tyranids
Ambush Predators and Assimilation Swarm (3 Detachment Points)
Priority Assets
Strike Force (2,000 Points)

ATTACHED UNITS

Attached unit 1

Tyranid Prime with Lash Whip (100 Points)
  • Attached as: Leader (Character)
  • 1x Lash whip
  • Enhancements: Parasitic Biomorphology

Hormagaunts (70 Points)
  • Attached as: Bodyguard (Battleline)
  • 10x Hormagaunts
     ◦ 10x Hormagaunt talons

CHARACTERS

The Swarmlord (210 Points)
  • Warlord
  • 1x Bone Sabres

OTHER DATASHEETS

Pyrovores (100 Points)
  • 3x Pyrovore
     ◦ 3x Chitin-barbed limbs
     ◦ 3x Flamespurt

Lictor (60 Points)
  • 1x Lictor claws and talons

Exported with New Recruit v37.21, Data Version: v3
"""


def test_header():
    army = ap.parse_list(ATTACHED_LIST)
    assert army.title == "Assim2k"
    assert army.points == "2,000"
    assert army.faction == "Tyranids"
    assert army.detachment == "Ambush Predators and Assimilation Swarm"
    assert army.disposition == "Priority Assets"


def test_units_and_model_counts():
    army = ap.parse_list(ATTACHED_LIST)
    counts = {u.name: u.models for u in army.units}
    assert counts == {"Tyranid Prime with Lash Whip": 1, "Hormagaunts": 10, "The Swarmlord": 1,
                      "Pyrovores": 3, "Lictor": 1}
    swarmlord = next(u for u in army.units if u.name == "The Swarmlord")
    assert swarmlord.warlord and swarmlord.character
    prime = army.units[0]
    assert prime.enhancement == "Parasitic Biomorphology"


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
    leaders = ap.resolve_leaders(army, {"Brood Warden": "Skitterlings"}, ask=False)
    assert leaders == {0: 1}


def test_base_key_and_candidates():
    assert ap.base_key("hormagaunt-2023-a.webp") == "hormagaunt"
    assert ap.base_key("hive-guard-b.webp") == "hiveguard"
    assert "tyranidprime" in ap.name_candidates("Tyranid Prime with Lash Whip")
    assert "swarmlord" in ap.name_candidates("The Swarmlord")
    assert "termagant" in ap.name_candidates("Termagants")


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
