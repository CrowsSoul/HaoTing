# -*- coding: utf-8 -*-
"""造一组带不同特征的零件，供 DFM 检查项做目标。

请求：{"dir": "...", "specs": [...] }   缺省用内置四件套
响应：{"ok": true, "parts": [{"name":..., "path":..., "faces":..., "bodies":...}]}

能力边界：只能用块、圆柱和布尔运算。回转体、拔模、倒圆暂时做不了。
"""
import json
import os
import traceback

REQ = os.environ["NXDRP_NX_REQUEST"]
RESP = os.environ["NXDRP_NX_RESPONSE"]
res = {"ok": True, "parts": []}


def emit():
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, default=str)


def build_block(part, F, ox, oy, oz, l, w, h):
    b = part.Features.CreateBlockFeatureBuilder(None)
    b.Type = F.BlockFeatureBuilder.Types.OriginAndEdgeLengths
    b.SetOriginAndLengths(NXOpen.Point3d(float(ox), float(oy), float(oz)), str(l), str(w), str(h))
    b.Commit()
    b.Destroy()
    return list(part.Bodies)[-1]


def build_cyl(part, F, x, y, z, dia, height, axis=(0.0, 0.0, 1.0)):
    c = part.Features.CreateCylinderBuilder(None)
    c.Type = F.CylinderBuilder.Types.AxisDiameterAndHeight
    c.Origin = NXOpen.Point3d(float(x), float(y), float(z))
    c.Direction = NXOpen.Vector3d(*[float(v) for v in axis])
    c.Diameter.Value = float(dia)
    c.Height.Value = float(height)
    c.Commit()
    c.Destroy()
    return list(part.Bodies)[-1]


def boolean(part, F, target, tool, operation):
    bf = part.Features.CreateBooleanBuilder(None)
    bf.Operation = operation
    bf.Target = target
    bf.Tool = tool
    bf.Commit()
    bf.Destroy()


def make_part(s, F, outdir, name, build_fn):
    path = os.path.join(outdir, name + ".prt")
    if os.path.exists(path):
        os.remove(path)
    r = s.Parts.NewDisplay(path, NXOpen.PartUnits.Millimeters)
    part = r[0] if isinstance(r, (tuple, list)) else r
    s.Parts.SetWork(part)
    try:
        build_fn(part, F)
    except Exception as exc:
        res.setdefault("errors", []).append([name, repr(exc)[:200]])
    faces = sum(len(list(b.GetFaces())) for b in part.Bodies)
    part.Save(NXOpen.BasePart.SaveComponents.FalseValue,
              NXOpen.BasePart.CloseAfterSave.FalseValue)
    res["parts"].append({"name": name, "path": path, "faces": faces,
                         "bodies": len(list(part.Bodies))})
    try:
        part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue,
                   NXOpen.BasePart.CloseModified.CloseModified, None)
    except Exception:
        pass


# ---------------- 四件套 ----------------

def f_plate_holes(part, F):
    """80×60×10 板，四个孔径都不在标准刀具系列里。"""
    base = build_block(part, F, 0, 0, 0, 80, 60, 10)
    holes = [(15, 15, 2.2), (40, 15, 3.7), (65, 15, 5.2), (25, 45, 6.25)]
    for x, y, d in holes:
        tool = build_cyl(part, F, x, y, -2, d, 14)
        boolean(part, F, base, tool, F.Feature.BooleanType.Subtract)
        base = list(part.Bodies)[0]


def f_thin_wall(part, F):
    """60×40×20 壳体，侧壁 2 mm、底 1.6 mm。"""
    base = build_block(part, F, 0, 0, 0, 60, 40, 20)
    pocket = build_block(part, F, 2, 2, 1.6, 56, 36, 18.4)
    boolean(part, F, base, pocket, F.Feature.BooleanType.Subtract)


def f_deep_slot(part, F):
    """40×30×15 块，中间一条 2 mm 宽、12 mm 深的窄槽。"""
    base = build_block(part, F, 0, 0, 0, 40, 30, 15)
    slot = build_block(part, F, 19, 0, 3, 2, 30, 12)
    boolean(part, F, base, slot, F.Feature.BooleanType.Subtract)


def f_bosses(part, F):
    """60×40×6 底板 + 两个圆柱凸台。"""
    base = build_block(part, F, 0, 0, 0, 60, 40, 6)
    for x, y, d, h in [(20, 20, 10.0, 8.0), (42, 20, 6.0, 4.0)]:
        boss = build_cyl(part, F, x, y, 6.0, d, h)
        boolean(part, F, base, boss, F.Feature.BooleanType.Unite)
        base = list(part.Bodies)[0]


SPECS = {
    "plate_holes": f_plate_holes,
    "thin_wall": f_thin_wall,
    "deep_slot": f_deep_slot,
    "bosses": f_bosses,
}


def main():
    with open(REQ, encoding="utf-8") as fh:
        req = json.load(fh)
    outdir = req["dir"]
    os.makedirs(outdir, exist_ok=True)
    names = req.get("names") or list(SPECS)

    import NXOpen

    global NXOpen  # noqa: PLW0603  build_* 通过闭包用到
    s = NXOpen.Session.GetSession()
    s.ListingWindow.Open()
    F = NXOpen.Features

    for name in names:
        make_part(s, F, outdir, name, SPECS[name])

    emit()


try:
    from NXOpen import *  # noqa: F401,F403
    import NXOpen
    import NXOpen.Features
    main()
except Exception as exc:
    res["ok"] = False
    res["fatal"] = repr(exc)
    res["traceback"] = traceback.format_exc()[-700:]
    emit()
