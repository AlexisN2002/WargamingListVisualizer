import math
from pathlib import Path

from PIL import Image, ImageDraw

import army_photo as ap
import board

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo_list.txt"
IMAGES = ROOT / "examples" / "demo_images"


def test_parse_base():
    assert board.parse_base(32) == (32, 32)
    assert board.parse_base("105x70") == (105, 70)
    assert board.parse_base("70x105mm") == (105, 70)
    assert board.parse_base("28.5mm") == (28.5, 28.5)
    assert board.parse_base("big") is None


def test_bases_lookup(tmp_path):
    f = tmp_path / "bases.json"
    f.write_text('{"Little Monster": 25, "Big Monster": "120x92", "_note": "ignored"}', encoding="utf-8")
    b = board.Bases(f)
    assert b.get("Little Monsters") == (25, 25)          # plural / singular
    assert b.get("The Big Monster") == (120, 92)
    assert b.get("Flying Monster Prime", "Little Monsters") == (25, 25)   # first name unknown -> second
    assert b.get("Medium Monster") is None


def test_maps_are_inside_the_battlefield():
    for name, m in board.MAPS.items():
        for key in ("a", "b"):
            for x, y in m[key]["poly"]:
                assert 0 <= x <= board.BOARD_W and 0 <= y <= board.BOARD_H, name
            cx, cy = board.zone_centroid(m[key])
            assert board.zone_contains(m[key], cx, cy) or name == "search-and-destroy", name
        assert len(m["objectives"]) == 5


def test_zone_cut_out():
    z = board.MAPS["search-and-destroy"]["a"]
    assert board.zone_contains(z, 5, 5)
    assert not board.zone_contains(z, 20, 28)        # inside the 9" circle round the centre
    assert not board.zone_contains(z, 30, 40)        # other player's quarter


def _setups(n=2):
    class Args:  # the parts of the CLI arguments board.run() reads
        images = str(IMAGES)
        enemy_images = str(IMAGES)
        leader, bases, terrain, output, seed = [], None, None, None, 0
        no_questions = no_disposition = no_open = True
        map, board_style, ppi = "crucible-of-battle", "tokens", 20
    return Args


def test_every_model_is_placed_inside_its_zone_without_overlaps():
    text = DEMO.read_text(encoding="utf-8")
    setups = []
    for i in range(2):
        army = ap.parse_list(text)
        lib = ap.ImageLibrary(IMAGES, {})
        r = ap.Renderer(lib, dict(ap.DEFAULTS), {})
        s = board.ArmySetup(army, IMAGES, dict(ap.DEFAULTS), lib, r, ap.resolve_leaders(army, {}, False),
                            board.Bases(IMAGES / "bases.json"))
        board.build_groups(s)
        setups.append(s)
    assert board.estimate_bases(setups) == []
    for name, m in board.MAPS.items():
        tokens = []
        for i, s in enumerate(setups):
            t, missing = board.place_army(s.groups, m["a" if i == 0 else "b"], i, tokens, None)
            assert missing == [], (name, missing)
            tokens += t
        assert len(tokens) == 2 * sum(len(g) for g in setups[0].groups)
        for t in tokens:
            rx, ry = board._radius(t.model)
            assert board.zone_contains(m["a" if t.army == 0 else "b"], t.x, t.y, rx, ry), name
        for i, a in enumerate(tokens):
            for b in tokens[i + 1:]:
                d = math.hypot(a.x - b.x, a.y - b.y)
                assert d >= board._radius(a.model)[0] + board._radius(b.model)[0] - 1e-6, name


def test_board_image_and_map_detection(tmp_path):
    b = board.draw_board(board.MAPS["hammer-and-anvil"], 20)
    img = Image.new("RGB", (b.width + 160, b.height + 120), (215, 215, 215))
    img.paste(b.convert("RGB"), (80, 60))
    ImageDraw.Draw(img).rectangle([78, 58, 80 + b.width + 1, 60 + b.height + 1], outline=(10, 10, 10), width=4)
    rect = board.find_board_rect(img)
    assert abs(rect[0] - 80) <= 4 and abs(rect[3] - (60 + b.height)) <= 4
    assert board.detect_map(img, rect, board.MAPS) == "hammer-and-anvil"


def test_board_cli(tmp_path):
    for style in ("tokens", "models"):
        out = tmp_path / f"board_{style}.png"
        rc = ap.main([str(DEMO), str(DEMO), "--board", "--map", "dawn-of-war", "--board-style", style,
                      "-i", str(IMAGES), "--enemy-images", str(IMAGES), "-o", str(out),
                      "--no-open", "--no-questions", "--ppi", "15"])
        assert rc == 0 and out.exists()


def test_layout_label_and_choice(tmp_path, monkeypatch):
    assert board.layout_label(Path("43_Take_and_Hold_vs_Take_and_Hold_Layout_A.png")) == \
        "Take and Hold vs Take and Hold, Layout A"
    folder = tmp_path / "images" / "layouts"
    folder.mkdir(parents=True)
    for name, m in (("01_X_Layout_A.png", "dawn-of-war"), ("02_X_Layout_B.png", "hammer-and-anvil")):
        board.draw_board(board.MAPS[m], 10).save(folder / name)
    monkeypatch.chdir(tmp_path)
    index = board.layout_index(board.MAPS)
    assert index == {"01_X_Layout_A.png": "dawn-of-war", "02_X_Layout_B.png": "hammer-and-anvil"}
    assert (folder / "index.json").exists()
    m, t = board.choose_battlefield(board.MAPS, "hammer-and-anvil", "random", 0)
    assert m == "hammer-and-anvil" and t.name == "02_X_Layout_B.png"
    m, t = board.choose_battlefield(board.MAPS, "", "01", 0)      # by number: map from the image
    assert m == "dawn-of-war" and t.name == "01_X_Layout_A.png"
    m, t = board.choose_battlefield(board.MAPS, "dawn-of-war", "none", 0)
    assert t is None


def test_transparent_layout_image():
    b = board.draw_board(board.MAPS["dawn-of-war"], 20).convert("RGBA")
    img = Image.new("RGBA", (b.width + 200, b.height + 200), (0, 0, 0, 0))
    img.alpha_composite(b, (100, 100))
    ImageDraw.Draw(img).line([(100, 40), (100 + b.width, 40)], fill=(150, 20, 20, 255), width=4)  # side bar
    rect = board.find_board_rect(img)
    assert abs(rect[0] - 100) <= 6 and abs(rect[2] - (100 + b.width)) <= 6
    assert abs(rect[1] - 100) <= 6 and abs(rect[3] - (100 + b.height)) <= 6
    assert board.detect_map(board.flatten(img), rect, board.MAPS) == "dawn-of-war"


def test_two_demo_armies_on_the_board(tmp_path):
    out = tmp_path / "vs.png"
    rc = ap.main([str(DEMO), str(ROOT / "examples" / "robot_list.txt"), "--board", "--map", "crucible-of-battle",
                  "-i", str(IMAGES), "--enemy-images", str(ROOT / "examples" / "robot_images"), "-o", str(out),
                  "--no-open", "--no-questions", "--no-terrain", "--ppi", "12"])
    assert rc == 0 and out.exists()
