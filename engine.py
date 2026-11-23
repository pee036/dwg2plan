"""dwg2plan engine: AutoCAD drawing (DXF, or DWG via a converter) -> backoffice-web-3d PlanSpec.

No AutoCAD program is needed to RUN this. A DWG is first turned into a DXF by a converter if one is
installed (AutoCAD's headless AcCoreConsole, or the ODA File Converter); a DXF needs nothing.

Frame of the output: metres, X right, Z down; zone corners are wall CENTRE-lines snapped to 5 cm.
"""
from __future__ import annotations

import glob
import logging
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import ezdxf
import numpy as np
import shapely
from ezdxf import path as ezpath
from scipy import ndimage
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

logging.disable(logging.CRITICAL)  # ezdxf warns about AutoCAD-only objects it skips; not useful here

SNAP = 0.05
HALF_WALL = 0.06

# Layers of this office's drawings (AP). Recipes can override them.
BODY = ["A-Walls8", "A-walls"]
OUTL = ["A-Walls2", "A-Walls1", "0_3 Cons Outside", "ELEV-0.10"]
DW = ["A-DW", "A-DWวงกบ", "AR_104_DW-DW", "เสาเอ็นประตู-หน้าต่าง"]


def snap(v: float) -> float:
    return round(round(v / SNAP) * SNAP, 2)


def largest(f):
    return max(f.geoms, key=lambda p: p.area) if f.geom_type == "MultiPolygon" else f


# ------------------------------------------------------------------ DWG -> DXF (only when needed)
class ConversionError(RuntimeError):
    pass


def _find_converters() -> list[tuple[str, str]]:
    found = []
    for p in glob.glob("/Applications/Autodesk/AutoCAD */AutoCAD *.app/Contents/Helpers/AcCoreConsole.app/Contents/MacOS/AcCoreConsole"):
        found.append(("accore-mac", p))
    for p in glob.glob(r"C:\Program Files\Autodesk\AutoCAD *\accoreconsole.exe"):
        found.append(("accore-win", p))
    for p in (shutil.which("ODAFileConverter"), "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"):
        if p and os.path.exists(p):
            found.append(("oda", p))
    return found


def ensure_dxf(path: str, workdir: str) -> str:
    """Return a DXF path. A .dxf is used as is; a .dwg is converted on a COPY (the original is never touched)."""
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    if src.suffix.lower() == ".dxf":
        return str(src)
    if src.suffix.lower() != ".dwg":
        raise ConversionError(f"unsupported file type {src.suffix!r}: give a .dxf or .dwg")
    work = Path(workdir)
    copy = work / "input.dwg"
    shutil.copyfile(src, copy)
    out = work / "input.dxf"
    errors = []
    for kind, exe in _find_converters():
        try:
            if kind.startswith("accore"):
                scr = work / "export.scr"
                scr.write_text(f"_.DXFOUT\n{out}\n_V\n2018\n16\n_.QUIT\n_Y\n")
                args = [exe, "/i", str(copy), "/s", str(scr)] + (["/l", "en-US"] if kind == "accore-mac" else [])
                subprocess.run(args, capture_output=True, timeout=600, check=False)
            else:  # ODA File Converter: <in dir> <out dir> <version> <type> <recurse> <audit> [filter]
                od = work / "oda_out"
                od.mkdir(exist_ok=True)
                subprocess.run([exe, str(work), str(od), "ACAD2018", "DXF", "0", "1", "input.dwg"],
                               capture_output=True, timeout=600, check=False)
                made = list(od.glob("*.dxf"))
                if made:
                    shutil.copyfile(made[0], out)
            if out.exists() and out.stat().st_size > 1000:
                return str(out)
            errors.append(f"{kind}: ran but produced no DXF")
        except Exception as exc:  # try the next converter
            errors.append(f"{kind}: {exc}")
    raise ConversionError(
        "Cannot read a .dwg here: no converter worked (" + "; ".join(errors or ["none installed"]) + "). "
        "Export a DXF once from AutoCAD (SAVEAS -> DXF 2018) or install the ODA File Converter, then pass the .dxf."
    )


# ------------------------------------------------------------------ the builder
class PlanBuilder:
    """Loads one plan block from a drawing and offers the geometry helpers a recipe needs."""

    def __init__(self, dxf_path: str, *, block: str, insert_x: tuple[float, float], sheet_bbox: tuple[float, float, float, float],
                 origin_x: float, origin_y: float = -218.51, window: tuple[float, float, float, float],
                 ignore_labels: tuple[str, ...] = (), room_tag: str = "ห้องพัก", res: float = 0.02):
        self.ox, self.oy = origin_x, origin_y
        self.X0, self.X1, self.Y0, self.Y1 = window
        self.R = res
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        cands = [e for e in msp if e.dxftype() == "INSERT" and e.dxf.name == block and insert_x[0] < e.dxf.insert.x < insert_x[1]]
        if not cands:
            raise KeyError(f"plan block {block!r} not found near x={insert_x} (is this the right drawing / sheet?)")
        self.geo = self._flatten_geo(cands[0])
        self.sheet = self._sheet_items(msp, sheet_bbox)
        self.labels = {s["attrs"][room_tag]: tuple(s["at"]) for s in self.sheet
                       if s.get("insert") == "SBroom" and room_tag in s.get("attrs", {}) and s["attrs"][room_tag] not in ignore_labels}
        self._build_barrier()

    # -- extraction ------------------------------------------------------------
    @staticmethod
    def _flat(ins, depth=0):
        out = []
        for v in ins.virtual_entities():
            if v.dxftype() == "INSERT" and depth < 5:
                out += PlanBuilder._flat(v, depth + 1)
            else:
                out.append(v)
        return out

    def _flatten_geo(self, plan_insert):
        geo = []
        for v in self._flat(plan_insert):
            t, layer = v.dxftype(), v.dxf.layer
            try:
                if t in ("LINE", "LWPOLYLINE", "ARC", "CIRCLE", "ELLIPSE"):
                    p = ezpath.make_path(v)
                    pts = [(round(q.x, 4), round(q.y, 4)) for q in p.flattening(0.01)]
                    closed = bool(getattr(v, "closed", False)) or t in ("CIRCLE", "ELLIPSE")
                    geo.append({"t": t, "l": layer, "pts": pts, "closed": closed})
                elif t == "TEXT":
                    geo.append({"t": "TEXT", "l": layer, "txt": v.dxf.text, "at": (round(v.dxf.insert.x, 3), round(v.dxf.insert.y, 3))})
            except Exception:
                pass
        return geo

    @staticmethod
    def _sheet_items(msp, bbox):
        x0, x1, y0, y1 = bbox
        items = []
        for e in msp:
            if e.dxftype() in ("TEXT", "MTEXT"):
                p = e.dxf.insert
                if x0 <= p.x <= x1 and y0 <= p.y <= y1:
                    txt = e.dxf.text if e.dxftype() == "TEXT" else e.plain_text()
                    items.append({"l": e.dxf.layer, "txt": txt, "at": (round(p.x, 3), round(p.y, 3))})
            elif e.dxftype() == "INSERT":
                p = e.dxf.insert
                if x0 <= p.x <= x1 and y0 <= p.y <= y1 and e.dxf.name in ("SBroom", "Sym_w-L", "Sym_v-L", "_SYM-DW"):
                    items.append({"l": e.dxf.layer, "insert": e.dxf.name, "at": (round(p.x, 3), round(p.y, 3)),
                                  "attrs": {a.dxf.tag: a.dxf.text for a in e.attribs}, "rot": e.dxf.rotation})
        return items

    # -- barrier mask: wall bodies + door/window frames + outline strokes + short wall gaps ----------
    @staticmethod
    def _shp(e, lb=None):
        p = e["pts"]
        if len(p) < 2:
            return None
        if e["closed"] and len(p) >= 3 and lb is None:
            pg = Polygon(p)
            return pg if pg.is_valid else pg.buffer(0)
        return LineString(p).buffer(lb or 0.02)

    def _build_barrier(self):
        g = self.geo
        wall_polys = [self._shp(e) for e in g if e["l"] in BODY and e["t"] == "LWPOLYLINE"]
        bar = list(wall_polys)
        for e in g:
            if e["t"] not in ("LWPOLYLINE", "LINE"):
                continue
            if e["l"] in DW:
                bar.append(self._shp(e, 0.03) if not e["closed"] else self._shp(e).buffer(0.02))
            elif e["l"] in OUTL:
                bar.append(self._shp(e, 0.03))
        bands = {"h": [], "v": []}
        for p in wall_polys:
            x0, y0, x1, y1 = p.bounds
            w, h = x1 - x0, y1 - y0
            if h < 0.32 and w > 0.12:
                bands["h"].append(((y0 + y1) / 2, x0, x1))
            elif w < 0.32 and h > 0.12:
                bands["v"].append(((x0 + x1) / 2, y0, y1))
        closers = []
        for kind, items in bands.items():          # close gaps (0.25-1.3 m) between collinear wall bands = doors / windows
            items.sort()
            cl = []
            for ax, a, b in items:
                if cl and abs(cl[-1][0] - ax) < 0.07:
                    cl[-1][1].append((a, b))
                else:
                    cl.append([ax, [(a, b)]])
            for ax, iv in cl:
                iv.sort()
                m = [list(iv[0])]
                for a, b in iv[1:]:
                    if a <= m[-1][1] + 0.01:
                        m[-1][1] = max(m[-1][1], b)
                    else:
                        if 0.25 <= a - m[-1][1] <= 1.3:
                            seg = [(m[-1][1], ax), (a, ax)] if kind == "h" else [(ax, m[-1][1]), (ax, a)]
                            closers.append(LineString(seg).buffer(0.04))
                        m.append([a, b])
        self.B = unary_union([b for b in bar + closers if b is not None])
        self.walls = unary_union(wall_polys)
        nx, ny = int((self.X1 - self.X0) / self.R), int((self.Y1 - self.Y0) / self.R)
        xs = self.X0 + (np.arange(nx) + 0.5) * self.R
        ys = self.Y0 + (np.arange(ny) + 0.5) * self.R
        XX, YY = np.meshgrid(xs, ys)
        self.mask = shapely.contains_xy(self.B, XX, YY)
        self.lab, _ = ndimage.label(~self.mask)

    # -- helpers for recipes ----------------------------------------------------
    def seed_xy(self, x, y):
        l = self.lab[int((y - self.Y0) / self.R), int((x - self.X0) / self.R)]
        if l == 0:
            raise ValueError(f"seed point ({x}, {y}) lies on a wall/barrier")
        return self.lab == l

    def seed_label(self, label):
        if label not in self.labels:
            raise KeyError(f"room label {label!r} not found on the sheet; available: {sorted(self.labels)}")
        return self.seed_xy(*self.labels[label])

    def region_poly(self, reg):
        """Rectilinear polygon of a boolean mask, smoothed: features < 30 cm (door frames, window bays) removed."""
        st = np.ones((15, 15), bool)
        reg = ndimage.binary_opening(ndimage.binary_closing(reg, structure=st), structure=st)
        boxes = []
        for iy in range(reg.shape[0]):
            row = reg[iy]
            if not row.any():
                continue
            d = np.diff(np.concatenate([[0], row.astype(int), [0]]))
            for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
                boxes.append(box(self.X0 + s * self.R, self.Y0 + iy * self.R, self.X0 + e * self.R, self.Y0 + (iy + 1) * self.R))
        return unary_union(boxes)

    @staticmethod
    def closed_union(parts, gap=0.12):
        """Join regions separated by a thin wall (for example a shower box beside a bathroom)."""
        return unary_union(parts).buffer(gap, join_style=2).buffer(-gap, join_style=2)

    @staticmethod
    def offset(faces):
        """Interior faces -> wall centre-line polygons (drawing space)."""
        return {k: largest(f).buffer(HALF_WALL, join_style=2) for k, f in faces.items()}

    def to_m(self, x, y):
        return (x - self.ox, self.oy - y)

    # -- wall lines, orthogonal polygons ---------------------------------------
    @staticmethod
    def _cluster(vals_w, tol=0.12):
        vals_w = sorted(vals_w)
        groups = []
        for v, w in vals_w:
            if groups and v - groups[-1][-1][0] <= tol:
                groups[-1].append((v, w))
            else:
                groups.append([(v, w)])
        return [sum(v * w for v, w in gr) / sum(w for _, w in gr) for gr in groups]

    def _wall_lines(self, face_map, min_len=0.6):
        xs_, ys_ = [], []
        for f in face_map.values():
            c = list(largest(f).exterior.coords)
            for (ax, ay), (bx, by) in zip(c, c[1:]):
                ln = math.hypot(bx - ax, by - ay)
                if ln < min_len:
                    continue
                if abs(ax - bx) < 0.04:
                    xs_.append(((ax + bx) / 2, ln))
                elif abs(ay - by) < 0.04:
                    ys_.append(((ay + by) / 2, ln))
        return self._cluster(xs_), self._cluster(ys_)

    @staticmethod
    def _snap_to_lines(v, lines, tol=0.2):
        best = min(lines, key=lambda l: abs(l - v))
        return best if abs(best - v) <= tol else v

    @staticmethod
    def _drop_collinear(out, exact):
        changed = True
        while changed and len(out) > 3:
            changed = False
            for i in range(len(out)):
                a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
                cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
                if (cross == 0) if exact else (abs(cross) < 1e-6):
                    out.pop(i)
                    changed = True
                    break
        return out

    def _orthogonalize(self, face):
        face = largest(face)
        pts = [(self._snap_to_lines(x, self.WX), self._snap_to_lines(y, self.WY)) for x, y in list(face.exterior.coords)[:-1]]
        out = []
        for p in pts:
            if not out or (abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6):
                out.append(p)
        if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-6 and abs(out[0][1] - out[-1][1]) < 1e-6:
            out.pop()
        return Polygon(self._drop_collinear(out, exact=False)).buffer(0)

    def _centre_polygon(self, off_poly):
        c = self._orthogonalize(off_poly)
        pts = [(snap(self.to_m(x, y)[0]), snap(self.to_m(x, y)[1])) for x, y in list(c.exterior.coords)[:-1]]
        out = []
        for p in pts:
            if not out or p != out[-1]:
                out.append(p)
        out = self._drop_collinear(out, exact=True)
        s = sum(out[i][0] * out[(i + 1) % len(out)][1] - out[(i + 1) % len(out)][0] * out[i][1] for i in range(len(out)))
        return out if s > 0 else out[::-1]       # positive shoelace area, as the app's polygonArea expects

    # -- the main step ----------------------------------------------------------
    def finalize(self, *, off, meta, openings, swing=None, explicit=None, adjust_open=None, final_fix=None,
                 plan_id, plan_name, ceiling=2.6):
        """off: {zone id: offset polygon in drawing space}; meta: {zone id: (kind, en, th, zh)} in output order;
        openings: [(type, (x, y) drawing space, width, note)]; swing: {note prefix: ((dx, dz) leaf opens towards, hinge point)}."""
        explicit = explicit or {}
        swing = swing or {}
        self.WX, self.WY = self._wall_lines(off)
        zones = []
        for zid, (kind, en, th, zh) in meta.items():
            poly = explicit[zid] if zid in explicit else [[x, z] for x, z in self._centre_polygon(off[zid])]
            zones.append({"id": zid, "name": {"en": en, "th": th, "zh": zh}, "kind": kind, "polygon": poly})
        polys = {z["id"]: Polygon(z["polygon"]) for z in zones}

        def edge_snap(p):
            best, pt = None, Point(p)
            for z in zones:
                ring = LineString(z["polygon"] + [z["polygon"][0]])
                d = ring.distance(pt)
                if best is None or d < best[0]:
                    q = ring.interpolate(ring.project(pt))
                    best = (d, (q.x, q.y))
            return best[1], best[0]

        def zone_at(px, pz):
            for zid, pg in polys.items():
                if pg.buffer(0.001).contains(Point(px, pz)):
                    return zid
            return None

        def wall_dir(at):
            best = None
            for z in zones:
                P = z["polygon"]
                for i in range(len(P)):
                    a, b = P[i], P[(i + 1) % len(P)]
                    ln = math.hypot(b[0] - a[0], b[1] - a[1])
                    if not ln:
                        continue
                    cross = abs((b[0] - a[0]) * (at[1] - a[1]) - (b[1] - a[1]) * (at[0] - a[0])) / ln
                    dot = (at[0] - a[0]) * (b[0] - a[0]) + (at[1] - a[1]) * (b[1] - a[1])
                    if cross < 0.05 and 0 <= dot <= ln * ln and (best is None or cross < best[0]):
                        best = (cross, ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln))
            return best[1] if best else (1, 0)

        def app_swing(o, open_vec, hinge_pt):
            """Mirror planEdit.doorGeometry: express the drawn swing as door:<in|out>:<left|right>."""
            dx, dz = wall_dir(o["at"])
            if dx < -1e-6 or (abs(dx) < 1e-6 and dz < 0):
                dx, dz = -dx, -dz
            n = (-dz, dx)
            area = lambda zid: abs(polys[zid].area) if zid else -1  # noqa: E731
            plus = zone_at(o["at"][0] + n[0] * 0.05, o["at"][1] + n[1] * 0.05)
            minus = zone_at(o["at"][0] - n[0] * 0.05, o["at"][1] - n[1] * 0.05)
            sign = 1 if area(plus) >= area(minus) else -1
            inward = (n[0] * sign, n[1] * sign)
            left = (-inward[1], inward[0])
            direction = "in" if (open_vec[0] * inward[0] + open_vec[1] * inward[1]) > 0 else "out"
            hx, hz = self.to_m(*hinge_pt)
            toh = (hx - o["at"][0], hz - o["at"][1])
            return direction, ("left" if (toh[0] * left[0] + toh[1] * left[1]) > 0 else "right")

        out_openings, snap_report = [], []
        for typ, (dx, dy), width, note in openings:
            mx, mz = self.to_m(dx, dy)
            (ex, ez), dist = edge_snap((mx, mz))
            o = {"type": typ, "at": [snap(ex), snap(ez)], "width": width}
            for key, (vec, hp) in swing.items():
                if note.startswith(key):
                    d, h = app_swing(o, vec, hp)
                    o["type"] = f"door:{d}:{h}"
            out_openings.append(o)
            snap_report.append((note, round(dist, 3)))

        open_edges, cov_rows = self._open_edges(zones)
        if adjust_open:
            open_edges = adjust_open(open_edges)
        if final_fix:
            final_fix(zones, out_openings, open_edges)

        spec = {
            "id": plan_id,
            "name": plan_name,
            "area": round(sum(abs(Polygon(z["polygon"]).area) for z in zones), 1),
            "zones": zones,
            "openings": out_openings,
            "open": open_edges,
            "fixtures": [],
            "ceiling": ceiling,
        }
        return spec, {"snap": snap_report, "coverage": cov_rows}

    def _open_edges(self, zones):
        """Wall-less edges: runs >= 0.5 m of a zone edge with no drawn wall or door/window frame within 12 cm."""
        cover = unary_union([self.walls] + [self._shp(e, 0.03) if not e["closed"] else self._shp(e).buffer(0.02)
                                            for e in self.geo if e["l"] in DW and e["t"] in ("LWPOLYLINE", "LINE")])
        cover_b = cover.buffer(0.12)
        open_edges, rows, seen = [], [], set()
        for z in zones:
            P = z["polygon"]
            for i in range(len(P)):
                a, b = P[i], P[(i + 1) % len(P)]
                ln = math.hypot(b[0] - a[0], b[1] - a[1])
                if ln < 0.3:
                    continue
                n = max(2, int(ln / 0.05))
                flags = []
                for k in range(n + 1):
                    t = k / n
                    x, y = (a[0] + (b[0] - a[0]) * t + self.ox, self.oy - (a[1] + (b[1] - a[1]) * t))
                    flags.append(not cover_b.contains(Point(x, y)))
                rows.append((z["id"], a, b, round(1 - sum(flags) / len(flags), 2)))
                k = 0
                while k <= n:
                    if flags[k]:
                        j = k
                        while j + 1 <= n and flags[j + 1]:
                            j += 1
                        if (j - k) * ln / n >= 0.5:
                            ta, tb = k / n, j / n
                            p = [snap(a[0] + (b[0] - a[0]) * ta), snap(a[1] + (b[1] - a[1]) * ta)]
                            q = [snap(a[0] + (b[0] - a[0]) * tb), snap(a[1] + (b[1] - a[1]) * tb)]
                            key = tuple(sorted([tuple(p), tuple(q)]))
                            if key not in seen and p != q:
                                seen.add(key)
                                open_edges.append([p, q])
                        k = j + 1
                    else:
                        k += 1
        return open_edges, rows


# ------------------------------------------------------------------ checks (the rules the backoffice editor relies on)
def check_spec(spec: dict) -> dict:
    """Python port of the editor's own rules. Returns {"errors": [...], "warnings": [...]}."""
    errors, warnings = [], []

    def area(poly):
        return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))) / 2

    if not isinstance(spec.get("zones"), list) or not spec["zones"]:
        errors.append("needs a non-empty zones array")
        return {"errors": errors, "warnings": warnings}
    polys = {}
    for z in spec["zones"]:
        a = area(z["polygon"])
        if a <= 0.25:
            errors.append(f"zone {z['id']}: area {a:.2f} m2 is not positive / too small")
        polys[z["id"]] = Polygon(z["polygon"])
        if not polys[z["id"]].is_valid:
            errors.append(f"zone {z['id']}: polygon is self-intersecting")
    ids = list(polys)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ov = polys[ids[i]].intersection(polys[ids[j]]).area
            if ov > 0.05:
                warnings.append(f"zones {ids[i]} and {ids[j]} overlap by {ov:.2f} m2")

    def on_edge(p, tol=0.05):
        for z in spec["zones"]:
            P = z["polygon"]
            for k in range(len(P)):
                a, b = P[k], P[(k + 1) % len(P)]
                dx, dz = b[0] - a[0], b[1] - a[1]
                l2 = dx * dx + dz * dz
                if not l2:
                    continue
                t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / l2
                if -0.01 <= t <= 1.01 and math.hypot(a[0] + t * dx - p[0], a[1] + t * dz - p[1]) < tol:
                    return True
        return False

    for i, o in enumerate(spec.get("openings", [])):
        if not on_edge(o["at"]):
            errors.append(f"opening #{i} ({o['type']}) at {o['at']} is not on a zone edge")
    total = round(sum(abs(area(z["polygon"])) for z in spec["zones"]), 1)
    if spec.get("area") is not None and abs(total - spec["area"]) > 0.11:
        warnings.append(f"declared area {spec['area']} differs from the zones' total {total}")
    return {"errors": errors, "warnings": warnings}


def preview_png(spec: dict, builder: PlanBuilder, path: str):
    """Overlay of the result on the drawing's wall linework (needs matplotlib)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 13))
    ax.set_aspect("equal")
    for e in builder.geo:
        if e["t"] in ("LWPOLYLINE", "LINE", "ARC") and e["l"] in BODY + DW + OUTL and len(e["pts"]) > 1:
            ax.plot(*zip(*[builder.to_m(x, y) for x, y in e["pts"]]), color="#888", lw=0.6)
    cols = plt.cm.tab20(np.linspace(0, 1, 20))
    for i, z in enumerate(spec["zones"]):
        P = z["polygon"] + [z["polygon"][0]]
        ax.fill(*zip(*P), color=cols[i % 20], alpha=0.35)
        ax.plot(*zip(*P), color="k", lw=1.4)
        c = Polygon(z["polygon"]).centroid
        ax.annotate(z["id"], (c.x, c.y), ha="center", fontsize=8)
    for o in spec["openings"]:
        base = o["type"].split(":")[0]
        ax.plot(*o["at"], "o", color={"door": "#b07a4a", "window": "#5b9bd5", "slider": "#3c9d8f"}[base], ms=8)
    for p, q in spec["open"]:
        ax.plot([p[0], q[0]], [p[1], q[1]], color="red", lw=3, ls=(0, (2, 2)))
    ax.invert_yaxis()
    ax.grid(True, alpha=0.2)
    fig.savefig(path, dpi=72, bbox_inches="tight")
    plt.close(fig)


def temp_workdir() -> str:
    return tempfile.mkdtemp(prefix="dwg2plan_")
