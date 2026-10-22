# -*- coding: utf-8 -*-
"""把零件导出为二进制 STL，供外部渲染。

请求：{"part": "...prt", "out": "...stl", "tol": 0.05}
响应：{"ok": true, "size": 12345}
"""
import json
import os
import traceback

REQ = os.environ["NXDRP_NX_REQUEST"]
RESP = os.environ["NXDRP_NX_RESPONSE"]
res = {"ok": True}


def emit():
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, default=str)


def main():
    with open(REQ, encoding="utf-8") as fh:
        req = json.load(fh)
    part_path = req["part"]
    out_stl = req["out"]
    tol = float(req.get("tol", 0.05))

    import NXOpen
    import NXOpen.UF

    s = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    part = s.Parts.OpenBaseDisplay(part_path)[0]

    bodies = [b for b in part.Bodies if not b.IsSheetBody]
    res["bodies"] = len(bodies)
    if not bodies:
        res["error"] = "没有实体"
        emit()
        return

    if os.path.exists(out_stl):
        os.remove(out_stl)

    handle = ufs.Std.OpenBinaryStlFile(out_stl, False, "nxdrp")
    res["handle"] = str(handle)[:60]

    written = 0
    for b in bodies:
        done = False
        for label, args in (
            ("null-tag", (handle, 0, b.Tag, 0.0, 0.0, tol)),
            ("none", (handle, None, b.Tag, 0.0, 0.0, tol)),
        ):
            try:
                ufs.Std.PutSolidInStlFile(*args)
                written += 1
                res["put_form"] = label
                done = True
                break
            except Exception as e:
                res.setdefault("put_err", []).append([label, repr(e)[:110]])
        if not done:
            break

    ufs.Std.CloseStlFile(handle)
    res["bodies_written"] = written
    res["exists"] = os.path.exists(out_stl)
    res["size"] = os.path.getsize(out_stl) if os.path.exists(out_stl) else 0
    emit()


try:
    main()
except Exception as exc:
    res["ok"] = False
    res["fatal"] = repr(exc)
    res["traceback"] = traceback.format_exc()[-700:]
    emit()
