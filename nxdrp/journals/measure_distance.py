# -*- coding: utf-8 -*-
"""NX 内部执行：批量最小距离测量（在 NX 进程内运行，只依赖标准库 + NXOpen）。

请求（NXDRP_NX_REQUEST）：
    {"part": "...prt", "kind": "face" | "body", "pairs": [[tagA, tagB], ...]}
响应（NXDRP_NX_RESPONSE）：
    {"ok": true, "pairs": [{"a":.., "b":.., "distance":.., "p1":[..], "p2":[..]}, ...],
     "errors": [{"a":.., "b":.., "error":".."}]}

为什么要批量：起一个 NX 进程约 28 秒，逐对调用会把 30 分钟的预算吃光。
一次把要测的配对全传进来，只起一次进程。
"""

import json
import os
import traceback

REQ_PATH = os.environ.get("NXDRP_NX_REQUEST", "")
RESP_PATH = os.environ.get("NXDRP_NX_RESPONSE", "")


def emit(payload):
    with open(RESP_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str)


def xyz(p):
    return [float(p.X), float(p.Y), float(p.Z)]


def main():
    with open(REQ_PATH, "r", encoding="utf-8") as fh:
        req = json.load(fh)

    import NXOpen

    session = NXOpen.Session.GetSession()
    session.ListingWindow.Open()
    part = session.Parts.OpenBaseDisplay(req["part"])[0]

    # 建 tag -> 对象的索引
    index = {}
    for body in part.Bodies:
        index[int(body.Tag)] = body
        for face in body.GetFaces():
            index[int(face.Tag)] = face

    out, errors = [], []
    for pair in req.get("pairs", []):
        a, b = int(pair[0]), int(pair[1])
        oa, ob = index.get(a), index.get(b)
        if oa is None or ob is None:
            errors.append({"a": a, "b": b, "error": "tag not found"})
            continue
        try:
            res = session.Measurement.GetMinimumDistance(oa, ob)
            out.append({
                "a": a, "b": b,
                "distance": float(res[0]),
                "p1": xyz(res[1]),
                "p2": xyz(res[2]),
            })
        except Exception as exc:
            errors.append({"a": a, "b": b, "error": repr(exc)})

    try:
        part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue,
                   NXOpen.BasePart.CloseModified.CloseModified, None)
    except Exception:
        pass

    session.ListingWindow.WriteLine("[nxdrp] measured %d pairs" % len(out))
    emit({"ok": True, "pairs": out, "errors": errors, "count": len(out)})


try:
    main()
except Exception as exc:
    emit({"ok": False, "error": "%r" % (exc,), "traceback": traceback.format_exc()})
