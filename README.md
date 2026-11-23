# dwg2plan

Turns a drawing sheet (**DXF** or **DWG**) into the **Plan JSON** that `backoffice-web-3d` imports.
It is a plain Python script. **The AutoCAD program is not needed** (never started, never touched).

## Install (once)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## Use
```bash
python dwg2plan.py --list                                   # recipes and sheets
python dwg2plan.py drawing.dxf --sheet A1-01 -o plan.json   # one sheet
python dwg2plan.py drawing.dwg --sheet all --out-dir out/   # every sheet of the recipe
python dwg2plan.py drawing.dxf --sheet A1-02 --json         # one JSON response on stdout (logs on stderr)
```
Options: `--preview` (check image), `--check-app ~/Documents/GitHub/backoffice-web-3d` (runs the backoffice's own
`planEdit.ts` on the result; needs Node 22.6+). Exit code 0 = ok, 1 = checks failed, 2 = bad arguments.

Import into the backoffice: paste `plan_<sheet>.json` into the *Plan JSON (metres; X right, Z down)* box
(new plan, kind **Unit floor plan**), or send `{"kind":"unit","spec": <file>}` to `POST /plans`.

## DWG input
A `.dwg` is converted to DXF on a **copy** (the original is never touched) by the first converter found:
AutoCAD's headless `AcCoreConsole` (macOS tested; Windows path untested), or the ODA File Converter (untested).
If none is installed: in AutoCAD run `SAVEAS` -> *AutoCAD 2018 DXF* once, and pass the `.dxf`.

## JSON response (`--json`)
```json
{"ok": true, "recipe": "usd2-s1090", "input": "...", "errors": [],
 "sheets": [{"sheet": "A1-01", "out": "...", "zones": 10, "openings": 14, "open_edges": 11, "area_m2": 80.5,
             "checks": {"errors": [], "warnings": []}, "spec": { ...the Plan JSON... }}]}
```

## What is automatic and what is not
Automatic: reading the drawing, finding walls / door and window frames, room regions from the room-name blocks,
wall centre-lines snapped to 5 cm, open (wall-less) edges from real wall coverage, door swing from the swing arcs.
By hand, once per project, in `recipes/<project>.py` (about 40 lines per sheet): how to split an open-plan region,
which enclosed boxes belong to which bathroom, the door/window positions and widths, plus assumptions
(ceiling 2.6 m, no fixtures, window sill/height left to the app's defaults).
A new project = copy `recipes/usd2_s1090.py`, change the numbers, register it in `RECIPES` in `dwg2plan.py`.
