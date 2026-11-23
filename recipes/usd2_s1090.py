"""Recipe for the drawing set USD2-S1090 (AP, "SINGLE HOUSE UPCOUNTRY 2021").

The engine is generic; this file holds what only a person can read off the drawing: which rooms to split out of an
open-plan region, which enclosed boxes belong to which bathroom, and the door/window positions with their swing.
To support another project, copy this file and change the numbers (about 40 lines per sheet).

Coordinates below are DRAWING space (the DXF's own units = metres here). Both floors share one plan frame, so they stack.
"""
from shapely.geometry import box
from shapely.ops import unary_union

from engine import PlanBuilder

DRAWING = "USD2-S1090"
LAYERS_NOTE = "AP layer names: A-Walls8, A-walls (wall bodies), A-DW (doors/windows), A-Walls2/1 (outlines)"


# ----------------------------------------------------------------------------- A1-01 ground floor
def build_a1_01(b: PlanBuilder):
    X0, X1, Y0, Y1 = b.X0, b.X1, b.Y0, b.Y1
    M = b.seed_label("ส่วนทานอาหาร")              # open-plan region: dining + living + stair hall + storage
    Mp = b.region_poly(M)
    D_Y, STAIR_X, BATH_L, BATH_B = -226.78, 564.96, 566.37, -224.50   # wall lines read off the plan
    living = Mp.intersection(box(X0, Y0, X1, D_Y))
    dining = Mp.intersection(box(X0, D_Y, STAIR_X, Y1))
    storage = Mp.intersection(box(BATH_L, D_Y, X1, BATH_B))
    stair = Mp.difference(unary_union([living, dining, storage]))
    bath_poly = unary_union([b.region_poly(b.seed_label("ห้องน้ำ 4")), box(567.60, -224.50, 568.50, -223.50)])
    stair = stair.difference(bath_poly.buffer(0.01)).intersection(box(X0, D_Y, BATH_L, Y1))

    faces = {
        "bedroom-4": b.region_poly(b.seed_label("ห้องนอน 4")),
        "kitchen": b.region_poly(b.seed_label("ห้องครัว")),
        "bath-4": bath_poly,
        "dining": dining,
        "living": living,
        "stair-hall": stair,
        "storage": storage,
        "porch": b.region_poly(b.seed_label("เฉลียง")),
        "carport": b.region_poly(b.seed_label("ที่จอดรถ(ด้านใน)")),
        "laundry-yard": box(564.95, -219.86, 568.50, -218.51),     # outline of the yard (A-Walls2), 1.15 m deep
    }
    meta = {
        "bedroom-4": ("room", "Bedroom 4", "ห้องนอน 4", "卧室 4"),
        "kitchen": ("kitchen", "Kitchen", "ห้องครัว", "厨房"),
        "bath-4": ("bath", "Bathroom 4", "ห้องน้ำ 4", "浴室 4"),
        "dining": ("room", "Dining", "ส่วนทานอาหาร", "用餐区"),
        "living": ("room", "Living", "ส่วนรับแขก", "客厅"),
        "stair-hall": ("room", "Stair hall", "โถงบันได", "楼梯厅"),
        "storage": ("room", "Storage", "เก็บของ", "储物间"),
        "porch": ("balcony", "Porch", "เฉลียง", "门廊"),
        "carport": ("balcony", "Carport (inner)", "ที่จอดรถ (ด้านใน)", "车位(内侧)"),
        "laundry-yard": ("balcony", "Laundry yard", "ลานซักล้าง", "洗衣院"),
    }
    openings = [   # (type, drawing-space centre, width, note). Doors: from the A-DW swing arcs. Windows: frame bands.
        ("door", (563.82, -223.407), 0.82, "WD1 bedroom<->dining"),
        ("door", (566.70, -222.897), 0.72, "WD2 kitchen<->bathroom"),
        ("door", (565.57, -219.81), 0.82, "WD3 kitchen<->laundry yard"),
        ("door", (565.57, -222.66), 0.82, "WD4 kitchen<->stair hall"),
        ("door", (565.57, -226.81), 0.82, "WD5 stair hall<->carport"),
        ("door", (568.60, -226.11), 0.72, "AD6 storage<->outside"),
        ("slider", (563.42, -229.76), 2.10, "AD1 living<->porch"),
        ("window", (563.42, -220.36), 1.50, "AW1 bedroom top"),
        ("window", (561.27, -222.96), 0.60, "AW4 bedroom left (lower)"),
        ("window", (561.27, -220.86), 0.60, "AW4 bedroom left (upper)"),
        ("window", (561.27, -225.06), 1.90, "AW2 dining left"),
        ("window", (561.87, -228.21), 1.50, "AW1 living left"),
        ("window", (566.92, -219.88), 1.30, "AW3 kitchen top"),
        ("window", (568.57, -224.01), 0.72, "AW5 bathroom right"),
    ]
    swing = {  # note prefix -> (direction the leaf opens towards in the plan frame [X right, Z down], hinge point)
        "WD1": ((0, -1), (564.229, -223.407)),
        "WD2": ((0, 1), (566.344, -222.897)),
        "WD3": ((0, -1), (565.157, -219.808)),
        "WD4": ((0, -1), (565.157, -222.658)),
        "WD5": ((0, 1), (565.157, -226.807)),
        "AD6": ((1, 0), (568.619, -226.467)),
    }
    return dict(
        off=b.offset(faces), meta=meta, openings=openings, swing=swing,
        # carport: the 0.4 m strip between the stair hall wall and the carport is wall + beam, not floor
        explicit={"carport": [[3.7, 8.3], [8.65, 8.3], [8.65, 11.3], [3.7, 11.3]]},
        plan_id="usd2-s1090-a1-01",
        plan_name={"en": "Single house USD2-S1090 - ground floor (A1-01)",
                   "th": "บ้านเดี่ยว USD2-S1090 - แปลนพื้นชั้นล่าง (A1-01)",
                   "zh": "独栋住宅 USD2-S1090 - 首层平面 (A1-01)"},
    )


# ----------------------------------------------------------------------------- A1-02 upper floor
def build_a1_02(b: PlanBuilder):
    X0, X1, Y0, Y1 = b.X0, b.X1, b.Y0, b.Y1
    # white shower boxes (enclosed, unlabeled in the drawing; floor +3.65) belong to the bathroom beside them
    WB = {"bath-2": (603.7, -220.6), "bath-3": (598.0, -224.2), "bath-1": (598.0, -225.9)}
    for k, (wx, wy) in WB.items():
        b.seed_xy(wx, wy)         # raises if the point is on a barrier (wrong drawing / moved sheet)

    def bath(label, k):
        return b.closed_union([b.region_poly(b.seed_label(label)), b.region_poly(b.seed_xy(*WB[k]))])

    faces = {
        "bedroom-3": b.region_poly(b.seed_label("ห้องนอน 3")),
        "bedroom-2": b.region_poly(b.seed_label("ห้องนอน 2")),
        "bath-2": bath("ห้องน้ำ 2", "bath-2"),
        "bath-3": bath("ห้องน้ำ 3", "bath-3"),
        "bath-1": bath("ห้องน้ำ 1", "bath-1"),
    }
    off = b.offset(faces)
    # open-plan region (stair hall + dressing room + bedroom 1): offset the WHOLE region first, then cut it on the
    # wall centre-lines, so the pieces share those lines exactly
    from engine import HALF_WALL, largest
    CUT_Y, CUT_X = -226.707, 600.17     # wall below the stair hall (grid D) / stub wall between dressing room and bedroom 1
    m2 = largest(b.region_poly(b.seed_label("โถงบันได"))).buffer(HALF_WALL, join_style=2)
    lower = m2.intersection(box(X0, Y0, X1, CUT_Y))
    off["stair-hall"] = m2.intersection(box(X0, CUT_Y, X1, Y1))
    off["dressing"] = lower.intersection(box(X0, Y0, CUT_X, CUT_Y))
    off["bedroom-1"] = lower.intersection(box(CUT_X, Y0, X1, CUT_Y))

    meta = {
        "bedroom-3": ("room", "Bedroom 3", "ห้องนอน 3", "卧室 3"),
        "bedroom-2": ("room", "Bedroom 2", "ห้องนอน 2", "卧室 2"),
        "bath-2": ("bath", "Bathroom 2", "ห้องน้ำ 2", "浴室 2"),
        "bath-3": ("bath", "Bathroom 3", "ห้องน้ำ 3", "浴室 3"),
        "bath-1": ("bath", "Bathroom 1", "ห้องน้ำ 1", "浴室 1"),
        "stair-hall": ("room", "Stair hall", "โถงบันได", "楼梯厅"),
        "dressing": ("room", "Dressing room", "แต่งตัว", "更衣室"),
        "bedroom-1": ("room", "Bedroom 1", "ห้องนอน 1", "卧室 1"),
        "balcony": ("balcony", "Balcony", "ระเบียง", "阳台"),
    }
    openings = [
        ("door", (600.72, -224.507), 0.82, "WD1 bedroom 3 <-> stair hall"),
        ("door", (601.82, -224.507), 0.82, "WD1 bedroom 2 <-> stair hall"),
        ("door", (600.57, -226.707), 0.82, "WD1 stair hall <-> bedroom 1"),
        ("door", (602.67, -221.30), 0.72, "WD2 bedroom 2 <-> bath 2"),
        ("door", (599.02, -223.432), 0.72, "WD2 bedroom 3 <-> bath 3"),
        ("door", (599.02, -226.582), 0.72, "WD2 dressing <-> bath 1"),
        ("slider", (599.87, -229.76), 1.90, "AD7 dressing <-> balcony"),
        ("window", (599.72, -220.36), 1.50, "AW1 bedroom 3 top"),
        ("window", (597.57, -220.86), 0.60, "AW4 bedroom 3 left (upper)"),
        ("window", (597.57, -222.86), 0.60, "AW4 bedroom 3 left (lower)"),
        ("window", (597.57, -223.86), 0.60, "AW6 bath 3 left"),
        ("window", (597.57, -226.16), 0.60, "AW6 bath 1 left"),
        ("window", (598.17, -227.26), 0.60, "AW4 dressing left"),
        ("window", (601.87, -219.86), 0.60, "AW6 bath 2 top (left)"),
        ("window", (603.57, -219.86), 0.60, "AW6 bath 2 top (right)"),
        ("window", (604.30, -222.38), 0.70, "AW4 bedroom 2 right (upper)"),
        ("window", (604.30, -223.99), 0.70, "AW4 bedroom 2 right (lower)"),
        ("window", (604.86, -225.60), 1.30, "AW7 stair hall right"),
        ("window", (604.30, -228.20), 1.50, "AW1 bedroom 1 right"),
        ("window", (602.07, -229.76), 0.60, "AW4.1 bedroom 1 bottom (left)"),
        ("window", (603.42, -229.76), 0.60, "AW4.1 bedroom 1 bottom (right)"),
    ]
    swing = {
        "WD1 bedroom 3": ((0, -1), (601.130, -224.507)),
        "WD1 bedroom 2": ((0, -1), (601.410, -224.507)),
        "WD1 stair hall": ((0, 1), (600.160, -226.707)),
        "WD2 bedroom 2": ((0, -1), (602.310, -221.282)),
        "WD2 bedroom 3": ((0, 1), (598.660, -223.432)),
        "WD2 dressing": ((0, -1), (598.660, -226.582)),
    }

    def adjust_open(edges):
        # the balcony's railings are thin outline strokes, not walls: its left, right and bottom edges are open
        edges = [e for e in edges if not (abs(e[0][1] - 11.25) < 1e-6 or e[0][1] >= 11.25 and e[1][1] >= 11.25)]
        return edges + [[[0.6, 11.25], [0.6, 12.3]], [[0.6, 12.3], [3.7, 12.3]], [[3.7, 12.3], [3.7, 11.25]]]

    def final_fix(zones, ops, edges):
        # the left exterior wall centre is exactly x = 0.00 (same as A1-01); clustering leaves it at 0.05
        fx = lambda v: 0.0 if abs(v - 0.05) < 1e-9 else v  # noqa: E731
        for z in zones:
            z["polygon"] = [[fx(x), zz] for x, zz in z["polygon"]]
        for o in ops:
            o["at"] = [fx(o["at"][0]), o["at"][1]]
        edges[:] = [[[fx(p[0]), p[1]], [fx(q[0]), q[1]]] for p, q in edges]

    return dict(
        off=off, meta=meta, openings=openings, swing=swing,
        # balcony: outline of the railing (A-Walls2 polylines, x 0.55-3.65, z 11.3-12.3); top edge on the wall line below the rooms
        explicit={"balcony": [[0.6, 11.25], [3.7, 11.25], [3.7, 12.3], [0.6, 12.3]]},
        adjust_open=adjust_open, final_fix=final_fix,
        plan_id="usd2-s1090-a1-02",
        plan_name={"en": "Single house USD2-S1090 - upper floor (A1-02)",
                   "th": "บ้านเดี่ยว USD2-S1090 - แปลนพื้นชั้นบน (A1-02)",
                   "zh": "独栋住宅 USD2-S1090 - 二层平面 (A1-02)"},
    )


SHEETS = {
    "A1-01": dict(
        title="ground floor / แปลนพื้นชั้นล่าง",
        load=dict(block="USD2-S1090_P1", insert_x=(560, 575), sheet_bbox=(551.5, 582.5, -236, -214.3),
                  origin_x=561.27, window=(560.8, 571.0, -232.0, -218.0)),
        build=build_a1_01),
    "A1-02": dict(
        title="upper floor / แปลนพื้นชั้นบน",
        load=dict(block="USD2-S1090_P2", insert_x=(598, 610), sheet_bbox=(585.5, 617.0, -236.5, -214.0),
                  origin_x=597.57, window=(596.5, 608.0, -232.5, -218.0), ignore_labels=("กันสาด",)),
        build=build_a1_02),
}
