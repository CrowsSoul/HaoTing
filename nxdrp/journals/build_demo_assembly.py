# -*- coding: utf-8 -*-
"""在 NX 里搭测试装配场景，给各检查器当靶子。

请求（NXDRP_NX_REQUEST）：
    {"src": "原始 .prt", "dir": "输出根目录",
     "scenes": [
        {"name": "demo_asm",    "placements": [["A", 0, 0, 0], ...]},
        {"name": "demo_normal", "placements": [...]},
        {"name": "demo_edge",   "placements": [...]},
     ]}
响应：
    {"ok": true, "scenes": [{"name":..., "assembly":..., "placed":[...]}]}

一次 NX 启动可以搭多个场景，省得反复起进程（每次约 30 秒）。
"""

import json
import os
import shutil
import traceback

REQ_PATH = os.environ.get("NXDRP_NX_REQUEST", "")
RESP_PATH = os.environ.get("NXDRP_NX_RESPONSE", "")

diag = {"steps": [], "errors": []}


def emit(payload):
    payload["diagnostics"] = diag
    with open(RESP_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str)


def step(name):
    diag["steps"].append(name)


#: 主场景：正常间距 / 0.15 贴近 / 半重叠 / 独立摆放
SCENE_MIXED = [
    ["A_BASE", 0.0, 0.0, 0.0],
    ["B_NEAR", 30.15, 0.0, 0.0],
    ["C_FAR", 60.0, 0.0, 0.0],
    ["D_NEAR2", 90.3, 0.0, 0.0],
    ["E_OVERLAP", 15.0, 0.0, 0.0],
    ["F_ALONE", 150.0, 0.0, 0.0],
]

#: 纯负样本：间距全部 20 mm，不该报任何间隙/干涉
SCENE_NORMAL = [
    ["A", 0.0, 0.0, 0.0],
    ["B", 50.0, 0.0, 0.0],
    ["C", 100.0, 0.0, 0.0],
    ["D", 150.0, 0.0, 0.0],
    ["E", 200.0, 0.0, 0.0],
]

#: 阈值边界：0.299 / 0.300 / 0.302，正好跨过 DFM-02 的 0.3
SCENE_EDGE = [
    ["A", 0.0, 0.0, 0.0],          #    0 .. 30
    ["B", 30.299, 0.0, 0.0],       # 30.299 .. 60.299   gap 0.299 -> 报
    ["C", 60.599, 0.0, 0.0],       # 60.599 .. 90.599   gap 0.300 -> 报（等于阈值）
    ["D", 90.901, 0.0, 0.0],       # 90.901 .. 120.901  gap 0.302 -> 不报
]

DEFAULT_SCENES = [
    {"name": "demo_asm", "placements": SCENE_MIXED},
    {"name": "demo_normal", "placements": SCENE_NORMAL},
    {"name": "demo_edge", "placements": SCENE_EDGE},
]


def main():
    with open(REQ_PATH, "r", encoding="utf-8") as fh:
        req = json.load(fh)

    src, outroot = req["src"], req["dir"]
    scenes = req.get("scenes") or DEFAULT_SCENES

    import NXOpen

    s = NXOpen.Session.GetSession()
    s.ListingWindow.Open()

    def identity():
        m = NXOpen.Matrix3x3()
        m.Xx, m.Xy, m.Xz = 1.0, 0.0, 0.0
        m.Yx, m.Yy, m.Yz = 0.0, 1.0, 0.0
        m.Zx, m.Zy, m.Zz = 0.0, 0.0, 1.0
        return m

    built = []
    for scene in scenes:
        name = scene["name"]
        placements = scene["placements"]
        outdir = os.path.join(outroot, name)
        os.makedirs(outdir, exist_ok=True)

        part_paths = []
        for tag, _x, _y, _z in placements:
            # NX 按文件名（不是路径）认零件，跨场景必须加前缀，否则 "File already exists"
            p = os.path.join(outdir, "%s_%s.prt" % (name, tag.lower()))
            if os.path.isfile(p):
                os.remove(p)
            shutil.copyfile(src, p)
            part_paths.append(p)

        asm_path = os.path.join(outdir, name + ".prt")
        if os.path.isfile(asm_path):
            os.remove(asm_path)
        res = s.Parts.NewDisplay(asm_path, NXOpen.PartUnits.Millimeters)
        asm = res[0] if isinstance(res, (tuple, list)) else res
        s.Parts.SetWork(asm)

        ca = asm.ComponentAssembly
        placed, positions = [], []
        for (tag, x, y, z), path in zip(placements, part_paths):
            try:
                opened = s.Parts.OpenBase(path)
                part = opened[0] if isinstance(opened, (tuple, list)) else opened
                ca.AddComponent(part, "MODEL", tag, NXOpen.Point3d(x, y, z), identity(), -1)
                placed.append(tag)
            except Exception as exc:
                diag["errors"].append([name, tag, repr(exc)[:140]])

        try:
            for k in list(ca.RootComponent.GetChildren()):
                gp = k.GetPosition()
                if isinstance(gp, (tuple, list)) and gp and gp[0] is not None:
                    positions.append([k.Name, round(gp[0].X, 3)])
        except Exception as exc:
            diag["errors"].append([name, "positions", repr(exc)])

        asm.Save(NXOpen.BasePart.SaveComponents.TrueValue,
                 NXOpen.BasePart.CloseAfterSave.FalseValue)
        step("%s: %d components" % (name, len(placed)))
        built.append({"name": name, "assembly": asm_path,
                      "placed": placed, "positions": positions})

    emit({"ok": True, "scenes": built, "count": len(built)})


try:
    main()
except Exception as exc:
    emit({"ok": False, "error": "%r" % (exc,), "traceback": traceback.format_exc()})
