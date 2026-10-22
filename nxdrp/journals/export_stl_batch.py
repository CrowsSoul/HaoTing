# -*- coding: utf-8 -*-
"""批量导出 STL：一次 NX 启动导出多个零件。

请求：{"jobs": [[part_path, out_stl], ...], "tol": 0.05}
响应：{"ok": true, "results": [[out_stl, size], ...]}
"""
import json
import os
import traceback

REQ = os.environ["NXDRP_NX_REQUEST"]
RESP = os.environ["NXDRP_NX_RESPONSE"]
res = {"ok": True, "results": []}


def emit():
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, default=str)


def main():
    with open(REQ, encoding="utf-8") as fh:
        req = json.load(fh)
    tol = float(req.get("tol", 0.05))
    jobs = req["jobs"]

    import NXOpen
    import NXOpen.UF

    s = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    for part_path, out_stl in jobs:
        try:
            if os.path.exists(out_stl):
                os.remove(out_stl)
            part = s.Parts.OpenBaseDisplay(part_path)[0]
            bodies = [b for b in part.Bodies if not b.IsSheetBody]
            handle = ufs.Std.OpenBinaryStlFile(out_stl, False, "nxdrp")
            n = 0
            for b in bodies:
                try:
                    ufs.Std.PutSolidInStlFile(handle, 0, b.Tag, 0.0, 0.0, tol)
                    n += 1
                except Exception as exc:
                    res.setdefault("errors", []).append([part_path, repr(exc)[:120]])
            ufs.Std.CloseStlFile(handle)
            res["results"].append([out_stl, os.path.getsize(out_stl) if os.path.exists(out_stl) else 0, n])
            try:
                part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue,
                           NXOpen.BasePart.CloseModified.CloseModified, None)
            except Exception:
                pass
        except Exception as exc:
            res.setdefault("errors", []).append([part_path, repr(exc)[:160]])

    emit()


try:
    main()
except Exception as exc:
    res["ok"] = False
    res["fatal"] = repr(exc)
    res["traceback"] = traceback.format_exc()[-600:]
    emit()
