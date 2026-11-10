# Changelog

## 2.0.0 (2026-11-10)

### New: battle-ready layout
- Models spread out like box art, seen from the front and a bit from above. One character with
  its unit stands in the front centre, the rest of the army stands around it in a half circle.
- Pick the character from a menu (`battle-ready.bat`, `--center ask`), by name
  (`--center "Name"`) or let the tool pick a random one (`--seed` repeats a pick).
- Further back means smaller and higher up. Units that would be hidden by the ones in front are
  moved back and towards the middle. Tunable with `perspective`, `tilt`, `curve` and `max_hidden`.
- The packed look is now called group photo (`--group-photo`). Two launchers replace
  `army-photo.bat`: `group-photo.bat` and `battle-ready.bat`.

### New: all New Recruit text exports
- GW, Roster (BattleScribe style), Compact (WTC), Minimal and Simple are detected automatically.
- Leaders written in the list are used in every format: `ATTACHED UNITS` (GW),
  `Leading` / `Attached to` with `[1]`, `[2]` for duplicate units (Compact), `• Leading:` /
  `• Leader:` (Minimal / Roster) and `+ 6x Unit` (Simple). Leader units with several models
  (e.g. a squad of characters) are drawn completely.
- `-m/--models "Unit=N"` and the `models` key in `army.json` for formats without model counts.

### Better images
- Wargear-aware: extra words in a file name (`spiky-monster-impaler.png`) are matched against the
  wargear and model names of the list, per model.
- All `-a`, `-b`, `-c` … variants of a model are mixed in a shuffled order.
- Every word of the unit name must appear in the file name, so `Winged Big Monster` finds
  `big-monster-wings.png`, and a plain `big-monster.png` is preferred over other kits.

### Other
- Shadows are off by default (`shadow_opacity`).
- The image folder is found automatically when `images/` has only one army in it.
- The console shows which list format was detected.
- Tests run on Python 3.10 and 3.13, on Linux and Windows.

## 1.0.0

- First release: group photo from the New Recruit GW export, leaders from `ATTACHED UNITS`,
  true scale, disposition icons, clipboard support.
