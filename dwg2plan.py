#!/usr/bin/env python3
"""dwg2plan - turn a drawing sheet (DXF or DWG) into the Plan JSON that backoffice-web-3d imports.

Runs as a plain script. The AutoCAD program is NOT needed (and is never started or touched).

  python dwg2plan.py drawing.dxf --sheet A1-01 -o plan.json
  python dwg2plan.py drawing.dwg --sheet all --out-dir out/ --preview
  python dwg2plan.py drawing.dxf --sheet A1-02 --json            # JSON response on stdout, for scripts / an API
  python dwg2plan.py --list

A .dwg needs a converter (AutoCAD's headless AcCoreConsole or the ODA File Converter) to become a DXF; with
neither installed, export a DXF once from AutoCAD and pass that.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine import ConversionError, PlanBuilder, check_spec, ensure_dxf, preview_png, temp_workdir  # noqa: E402

RECIPES = {"usd2-s1090": "recipes.usd2_s1090"}


def log(*a):
    print(*a, file=sys.stderr)


def load_recipe(name: str):
    if name not in RECIPES:
        raise KeyError(f"unknown recipe {name!r}; available: {sorted(RECIPES)}")
    return importlib.import_module(RECIPES[name])


def run_app_check(spec_path: str, app_repo: str) -> tuple[bool, str]:
    """Run the backoffice's own planEdit.ts on the JSON (needs Node >= 22.6)."""
    node = shutil.which("node")
    if not node:
        return False, "node not found; skipped the backoffice check"
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", os.path.join(HERE, "validate_with_app.mts"), spec_path, app_repo],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Drawing sheet (DXF/DWG) -> backoffice Plan JSON", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("input", nargs="?", help=".dxf or .dwg file")
    ap.add_argument("--recipe", default="usd2-s1090", help="project recipe (default: usd2-s1090)")
    ap.add_argument("--sheet", default="all", help="sheet id such as A1-01, or 'all'")
    ap.add_argument("-o", "--out", help="output JSON file (one sheet)")
    ap.add_argument("--out-dir", help="output folder (plan_<sheet>.json per sheet)")
    ap.add_argument("--json", action="store_true", help="print one JSON response to stdout (logs go to stderr)")
    ap.add_argument("--preview", nargs="?", const="auto", help="write a check image (PNG) next to the JSON, or to this path")
    ap.add_argument("--check-app", metavar="BACKOFFICE_REPO", help="also run backoffice-web-3d's own planEdit.ts on the result")
    ap.add_argument("--list", action="store_true", help="list recipes and sheets")
    a = ap.parse_args()

    try:
        recipe = load_recipe(a.recipe)
    except KeyError as exc:
        log(exc)
        return 2
    if a.list or not a.input:
        for rid in RECIPES:
            m = load_recipe(rid)
            print(f"{rid}  (drawing {m.DRAWING})")
            for sid, sh in m.SHEETS.items():
                print(f"  {sid}  {sh['title']}")
        return 0

    sheets = list(recipe.SHEETS) if a.sheet == "all" else [a.sheet]
    for s in sheets:
        if s not in recipe.SHEETS:
            log(f"unknown sheet {s!r}; available: {list(recipe.SHEETS)}")
            return 2
    if a.out and len(sheets) != 1:
        log("--out needs exactly one --sheet; use --out-dir for several")
        return 2

    response = {"ok": True, "recipe": a.recipe, "input": os.path.abspath(a.input), "sheets": [], "errors": []}
    work = temp_workdir()
    try:
        dxf = ensure_dxf(a.input, work)
        for sid in sheets:
            sh = recipe.SHEETS[sid]
            log(f"[{sid}] {sh['title']}")
            builder = PlanBuilder(dxf, **sh["load"])
            spec, info = builder.finalize(**sh["build"](builder))
            checks = check_spec(spec)
            out_path = a.out or os.path.join(a.out_dir or os.getcwd(), f"plan_{sid}.json")
            if a.out_dir:
                os.makedirs(a.out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, ensure_ascii=False, indent=2)
            entry = {"sheet": sid, "out": os.path.abspath(out_path), "zones": len(spec["zones"]), "openings": len(spec["openings"]),
                     "open_edges": len(spec["open"]), "area_m2": spec["area"], "checks": checks, "spec": spec}
            if a.preview:
                png = out_path[:-5] + ".png" if a.preview == "auto" else a.preview
                preview_png(spec, builder, png)
                entry["preview"] = os.path.abspath(png)
            if a.check_app:
                ok, text = run_app_check(out_path, os.path.expanduser(a.check_app))
                entry["app_check"] = {"ok": ok, "output": text}
                if not ok:
                    checks["errors"].append("backoffice planEdit check failed: " + text.splitlines()[-1] if text else "check failed")
            log(f"    {len(spec['zones'])} zones, {len(spec['openings'])} openings, {len(spec['open'])} open edges, {spec['area']} m2 -> {out_path}")
            for w in checks["warnings"]:
                log("    warning:", w)
            for e in checks["errors"]:
                log("    ERROR:", e)
            if checks["errors"]:
                response["ok"] = False
            response["sheets"].append(entry)
    except (ConversionError, KeyError, ValueError, FileNotFoundError) as exc:
        response["ok"] = False
        response["errors"].append(f"{type(exc).__name__}: {exc}")
        log("ERROR:", exc)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if a.json:
        print(json.dumps(response, ensure_ascii=False))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
