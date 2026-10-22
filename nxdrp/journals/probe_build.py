# -*- coding: utf-8 -*-
"""试造：块 + 圆柱（设尺寸）+ 布尔减，做成一个带孔的板。"""
import json
import os
import traceback

REQ = os.environ["NXDRP_NX_REQUEST"]
RESP = os.environ["NXDRP_NX_RESPONSE"]
res = {"ok": True, "steps": []}


def emit():
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, default=str)


def step(name, fn):
    try:
        v = fn()
        res["steps"].append([name, "ok", str(v)[:60] if v is not None else ""])
        return v
    except Exception as e:
        res["steps"].append([name, "fail", repr(e)[:170]])
        return None


def main():
    with open(REQ, encoding="utf-8") as fh:
        req = json.load(fh)
    outdir = req["dir"]
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "probe_hole.prt")
    if os.path.exists(path):
        os.remove(path)

    import NXOpen

    s = NXOpen.Session.GetSession()
    r = s.Parts.NewDisplay(path, NXOpen.PartUnits.Millimeters)
    part = r[0] if isinstance(r, (tuple, list)) else r
    s.Parts.SetWork(part)
    F = NXOpen.Features

    b = part.Features.CreateBlockFeatureBuilder(None)
    b.Type = F.BlockFeatureBuilder.Types.OriginAndEdgeLengths
    b.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "80", "60", "10")
    b.Commit()
    b.Destroy()
    block = list(part.Bodies)[0]

    cyl = part.Features.CreateCylinderBuilder(None)
    cyl.Type = F.CylinderBuilder.Types.AxisDiameterAndHeight
    cyl.Origin = NXOpen.Point3d(20.0, 20.0, -5.0)
    cyl.Direction = NXOpen.Vector3d(0.0, 0.0, 1.0)

    # 尺寸是 Expression，试着从 .Value 下手
    step("diam value", lambda: setattr(cyl.Diameter, "Value", 6.25))
    step("height value", lambda: setattr(cyl.Height, "Value", 20.0))
    res["diam_after"] = step("diam get", lambda: str(cyl.Diameter))
    cyl.Commit()
    cyl.Destroy()

    tools = [x for x in part.Bodies if x.Tag != block.Tag]
    res["bodies_before"] = len(list(part.Bodies))

    bf = part.Features.CreateBooleanBuilder(None)
    bf.Operation = F.Feature.BooleanType.Subtract
    bf.Target = block
    if tools:
        step("tool", lambda: setattr(bf, "Tool", tools[0]))
    step("bool commit", lambda: bf.Commit())
    try:
        bf.Destroy()
    except Exception:
        pass

    res["bodies_after"] = len(list(part.Bodies))
    res["faces"] = sum(len(list(x.GetFaces())) for x in part.Bodies)
    res["face_types"] = [
        str(f.SolidFaceType) for f in list(list(part.Bodies)[0].GetFaces())
    ][:12]
    part.Save(NXOpen.BasePart.SaveComponents.FalseValue,
              NXOpen.BasePart.CloseAfterSave.FalseValue)
    emit()


try:
    main()
except Exception as exc:
    res["ok"] = False
    res["fatal"] = repr(exc)
    res["traceback"] = traceback.format_exc()[-600:]
    emit()
