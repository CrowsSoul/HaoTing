# -*- coding: utf-8 -*-
"""NX 内部执行的几何提取 journal（在 NX 进程内运行，只依赖标准库 + NXOpen）。

不要在本文件里 import nxdrp —— NX 用的是它自带的 Python 3.12，
宿主代码的 sys.path 在里面不可见。全部通信通过两个环境变量指定的 JSON 文件：

    输入  NXDRP_NX_REQUEST   {"part": "...prt", "model_id": "...", "options": {...}}
    输出  NXDRP_NX_RESPONSE  {"ok": true, "model": {...ModelBundle...}, "diagnostics": {...}}

调试时可手动运行：
    set NXDRP_NX_REQUEST=D:\\req.json
    set NXDRP_NX_RESPONSE=D:\\resp.json
    "%UGII_BASE_DIR%\\NXBIN\\run_journal.exe" nxdrp\\journals\\extract_geometry.py

设计原则：任何一段失败都不能让整次解析失败。逐段 try/except，把问题写进 diagnostics，
让下游知道「哪些数据不可用」，而不是拿到一份看起来正常、实际缺字段的模型。
"""

import json
import os
import sys
import time
import traceback

import NXOpen
import NXOpen.UF

REQ_PATH = os.environ.get("NXDRP_NX_REQUEST", "")
RESP_PATH = os.environ.get("NXDRP_NX_RESPONSE", "")

#: UF 面类型码 -> 名字（以 UF 为准，NXOpen 的 SolidFaceType 枚举码与之不对应）
UF_TYPE_NAMES = {
    16: "planar", 17: "cylindrical", 18: "conical", 19: "spherical", 20: "toroidal",
    21: "swept", 22: "bspline", 23: "planar", 24: "cylindrical", 25: "conical",
    26: "spherical", 27: "toroidal", 28: "blend", 29: "offset",
}

#: NXOpen SolidFaceType 数值映射（仅在没有 UF 数据时兜底）
FACE_TYPE_MAP = {
    1: "planar",
    2: "cylindrical",
    3: "conical",
    4: "spherical",
    5: "toroidal",
    6: "general",
    7: "blend",
    8: "bsurface",
    9: "offset",
}

UNKNOWN_CODES = set()

#: NX UF 面类型码（UF_MODL_*_FACE）
UF_PLANAR = 16

#: UF 曲线类型码（AskEdgeType 的返回值）常见几种
UF_EDGE_TYPES = {3001: "line", 3002: "arc", 3003: "conic",
                 3004: "spline", 3005: "curve_on_surface"}

#: 材料可能挂在哪些属性名上
MATERIAL_ATTRS = ("MATERIAL", "Material", "material", "材料", "MAT", "MATL")
UF_ROTATIONAL = (17, 18, 19, 20)   # 圆柱 / 圆锥 / 球 / 环面


def emit(payload):
    with open(RESP_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str)


def _apply_point(pt, tf):
    """点乘以 4x4 变换。"""
    if tf is None or pt is None:
        return list(pt) if pt else None
    x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
    return [
        tf[0][0] * x + tf[0][1] * y + tf[0][2] * z + tf[0][3],
        tf[1][0] * x + tf[1][1] * y + tf[1][2] * z + tf[1][3],
        tf[2][0] * x + tf[2][1] * y + tf[2][2] * z + tf[2][3],
    ]


def _apply_dir(d, tf):
    """方向只转不平移。"""
    if tf is None or d is None:
        return list(d) if d else None
    x, y, z = float(d[0]), float(d[1]), float(d[2])
    return [
        tf[0][0] * x + tf[0][1] * y + tf[0][2] * z,
        tf[1][0] * x + tf[1][1] * y + tf[1][2] * z,
        tf[2][0] * x + tf[2][1] * y + tf[2][2] * z,
    ]


def _apply_bbox(b, tf):
    """包围盒变换：8 个角点变换后重新取 AABB。"""
    if tf is None or not b:
        return b
    corners = [(b["xmin"], b["ymin"], b["zmin"]), (b["xmax"], b["ymin"], b["zmin"]),
               (b["xmin"], b["ymax"], b["zmin"]), (b["xmax"], b["ymax"], b["zmin"]),
               (b["xmin"], b["ymin"], b["zmax"]), (b["xmax"], b["ymin"], b["zmax"]),
               (b["xmin"], b["ymax"], b["zmax"]), (b["xmax"], b["ymax"], b["zmax"])]
    pts = [_apply_point(c, tf) for c in corners]
    return bbox_from_points(pts)


def _read_material(part_obj, diagnostics):
    """从零件属性里读材料；读不到返回 None。不猜、不编。"""
    if part_obj is None:
        return None
    for title in MATERIAL_ATTRS:
        try:
            v = part_obj.GetStringAttribute(title)
            if v:
                return str(v)
        except Exception:
            pass
    try:
        for attr in part_obj.GetUserAttributes() or []:
            title = getattr(attr, "Title", "")
            if title in MATERIAL_ATTRS:
                try:
                    return str(attr.GetStringValue())
                except Exception:
                    pass
    except Exception as exc:
        diagnostics["warnings"].append("material: %r" % (exc,))
    return None


def enum_to_int(value):
    """NX 枚举成员不能直接 int()，要先转字符串。实测 NX 2606 的 str() 返回数字串。"""
    if value is None:
        return 0
    try:
        return int(value)
    except Exception:
        pass
    try:
        return int(str(value).strip())
    except Exception:
        return 0


def face_type_name(code):
    name = FACE_TYPE_MAP.get(int(code))
    if name is None:
        UNKNOWN_CODES.add(int(code))
        return "unknown_%d" % int(code)
    return name


def point_xyz(p):
    """NX Point3d -> (x, y, z)。"""
    return (float(p.X), float(p.Y), float(p.Z))


def bbox_from_points(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return {
        "xmin": min(xs), "ymin": min(ys), "zmin": min(zs),
        "xmax": max(xs), "ymax": max(ys), "zmax": max(zs),
    }


def alternate_solution(NXOpen):
    """返回 (enum值, 是否半径)。不同 NX 版本枚举名可能不同，逐个试。"""
    cls = getattr(NXOpen, "MeasurementAlternateFace", None)
    if cls is not None:
        for name, is_radius in (("Radius", True), ("Diameter", False)):
            val = getattr(cls, name, None)
            if val is not None:
                return val, is_radius
    return 0, True


def main():
    t0 = time.time()
    diagnostics = {"journal": "extract_geometry", "warnings": [], "sections": {}}

    if not REQ_PATH or not os.path.isfile(REQ_PATH):
        emit({"ok": False, "error": "缺少 NXDRP_NX_REQUEST 或文件不存在", "diagnostics": diagnostics})
        return
    with open(REQ_PATH, "r", encoding="utf-8") as fh:
        req = json.load(fh)

    part_path = req.get("part", "")
    model_id = req.get("model_id") or os.path.splitext(os.path.basename(part_path))[0]
    options = req.get("options") or {}
    measure_faces = bool(options.get("measure_faces", True))
    max_faces = int(options.get("max_faces", 20000))
    collect_edges = bool(options.get("collect_edges", True))
    collect_assembly = bool(options.get("collect_assembly", True))

    try:
        import NXOpen
    except Exception as exc:
        emit({"ok": False, "error": "NXOpen 导入失败: %r" % (exc,), "diagnostics": diagnostics})
        return

    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    session.ListingWindow.Open()
    session.ListingWindow.WriteLine("[nxdrp] extracting %s" % part_path)

    opened = session.Parts.OpenBaseDisplay(part_path)
    part = opened[0] if isinstance(opened, (tuple, list)) else opened

    # ---------------- 基本属性 ----------------
    units = "mm"
    try:
        actual_units = str(part.PartUnits)
        inch_tokens = set()
        for holder in (getattr(NXOpen, "BasePartUnits", None), getattr(NXOpen, "PartUnits", None)):
            if holder is None:
                continue
            val = getattr(holder, "Inches", None)
            if val is not None:
                inch_tokens.add(str(val))
        if actual_units in inch_tokens:
            units = "inch"
        diagnostics["part_units_raw"] = actual_units
    except Exception as exc:
        diagnostics["warnings"].append("单位判定失败: %r" % (exc,))

    nx_version = ""
    try:
        nx_version = session.GetEnvironmentVariableValue("UGII_VERSION") or ""
    except Exception:
        pass

    model = {
        "schema_version": "1.0.0",
        "model_id": model_id,
        "source": req.get("part", ""),
        "nx_version": nx_version,
        "units": units,
        "created_at": "",
        "generator": "nxdrp.journals.extract_geometry",
        "parts": [],
        "faces": [],
        "edges": [],
        "occurrences": [],
        "adjacency": [],
        "diagnostics": {},
        "meta": {},
    }

    # ---------------- 实体与面 ----------------
    meas = session.Measurement
    alt, is_radius = alternate_solution(NXOpen)

    n_bodies = 0
    n_faces = 0
    face_seq = 0
    edge_seq = 0
    tag2face = {}
    _used_face_ids = []
    body_edges = []

    # 装配体本身没有 body：要按组件（occurrence）展开到各自的原型零件
    units = []          # (part_id, body, occurrence_path)
    root_component = None
    try:
        root_component = part.ComponentAssembly.RootComponent
    except Exception:
        root_component = None

    if root_component is not None:
        stack = [root_component]
        ci = 0
        while stack and ci < 2000:
            node = stack.pop()
            for child in list(node.GetChildren()):
                ci += 1
                try:
                    proto = child.Prototype.OwningPart
                except Exception:
                    proto = None
                if proto is None:
                    continue
                try:
                    pbodies = list(proto.Bodies)
                except Exception:
                    pbodies = []
                ctf = None
                try:
                    gp = child.GetPosition()
                    if isinstance(gp, (tuple, list)) and len(gp) >= 2 and gp[0] is not None:
                        loc, ori = gp[0], gp[1]
                        ctf = [
                            [float(getattr(ori, "Xx", 1.0)), float(getattr(ori, "Xy", 0.0)),
                             float(getattr(ori, "Xz", 0.0)), float(loc.X)],
                            [float(getattr(ori, "Yx", 0.0)), float(getattr(ori, "Yy", 1.0)),
                             float(getattr(ori, "Yz", 0.0)), float(loc.Y)],
                            [float(getattr(ori, "Zx", 0.0)), float(getattr(ori, "Zy", 0.0)),
                             float(getattr(ori, "Zz", 1.0)), float(loc.Z)],
                            [0.0, 0.0, 0.0, 1.0],
                        ]
                except Exception as exc:
                    diagnostics["warnings"].append("component transform: %r" % (exc,))
                for k, b in enumerate(pbodies):
                    pid = "P%02d" % ci if len(pbodies) == 1 else "P%02d_%d" % (ci, k + 1)
                    units.append((pid, b, child.Name or "", ctf, proto))
                stack.append(child)
        diagnostics["sections"]["assembly_mode"] = "expanded %d components" % ci

    if not units:
        try:
            for i, b in enumerate(part.Bodies):
                units.append(("P%02d" % (i + 1), b, "", None, part))
        except Exception as exc:
            diagnostics["sections"]["bodies"] = "error: %r" % (exc,)

    n_bodies = len(units)
    for bi, (part_id, body, occ_name, ctf, unit_part) in enumerate(units):
        is_sheet = False
        try:
            is_sheet = bool(body.IsSheetBody)
        except Exception:
            pass

        p = {
            "part_id": part_id,
            "name": "",
            "journal_id": "",
            "part_file": req.get("part", ""),
            "material": _read_material(unit_part, diagnostics) or "",
            "body_type": "sheet" if is_sheet else "solid",
            "is_sheet": is_sheet,
            "volume": None,
            "mass": None,
            "area": None,
            "bbox": None,
            "face_count": 0,
            "edge_count": 0,
            "occurrence_path": occ_name,
        }
        try:
            p["journal_id"] = body.JournalIdentifier or ""
        except Exception:
            pass
        try:
            p["name"] = body.Name or ""
        except Exception:
            pass

        # 质量属性 / 包围盒
        try:
            props = meas.GetBodyProperties([body], 0.99, False)
            mass_props = props[0] if isinstance(props, (tuple, list)) else None
            if mass_props and len(mass_props) >= 8:
                p["area"] = float(mass_props[0])
                p["volume"] = float(mass_props[1])
                p["mass"] = float(mass_props[6]) if mass_props[6] is not None else None
        except Exception as exc:
            diagnostics["sections"]["body_props"] = "warn: %r" % (exc,)

        try:
            box = meas.GetBoundingBoxProperties([body], 0, NXOpen.Point3d(0.0, 0.0, 0.0), False)
            pts = [point_xyz(pt) for pt in box[0]]
            p["bbox"] = _apply_bbox(bbox_from_points(pts), ctf)
        except Exception as exc:
            diagnostics["sections"]["body_bbox"] = "warn: %r" % (exc,)

        # 面
        try:
            faces = list(body.GetFaces())
        except Exception as exc:
            diagnostics["sections"]["faces"] = "error: %r" % (exc,)
            faces = []

        for face in faces:
            if n_faces >= max_faces:
                diagnostics["warnings"].append("面数超过上限 %d，已截断" % max_faces)
                break
            face_seq += 1
            try:
                tag = int(face.Tag)
            except Exception:
                tag = face_seq
            face_id = "F%d" % tag
            if face_id in _used_face_ids:
                _dup = _used_face_ids.count(face_id) + 1
                face_id = "F%d-%d" % (tag, _dup)
            code = 0
            try:
                code = enum_to_int(face.SolidFaceType)
            except Exception:
                pass

            rec = {
                "face_id": face_id,
                "part_id": part_id,
                "tag": tag,
                "solid_face_type": face_type_name(code),
                "solid_face_code": code,
                "uf_face_type": 0,
                "point": None,
                "normal": None,
                "axis": None,
                "area": None,
                "perimeter": None,
                "radius_diameter": None,
                "is_radius": is_radius,
                "cog": None,
                "bbox": None,
                "edge_count": 0,
            }

            # 面几何：平面取法向，回转面取轴向 + 轴线上一点
            try:
                fd = ufs.Modeling.AskFaceData(tag)
                rec["uf_face_type"] = int(fd[0])
                rec["point"] = [float(v) for v in fd[1]]
                direction = [float(v) for v in fd[2]]
                fname = face_type_name(code)
                if fname == "planar":
                    rec["normal"] = direction
                elif fname in ("cylindrical", "conical", "spherical", "toroidal"):
                    rec["axis"] = direction
                    r = float(fd[4])
                    if r > 1e-9 and not rec["radius_diameter"]:
                        rec["radius_diameter"] = r
                        rec["is_radius"] = True
            except Exception as exc:
                diagnostics["sections"].setdefault("face_data", "warn: %r" % (exc,))

            if measure_faces:
                try:
                    res = meas.GetFaceProperties([face], 0.99, alt, False)
                    rec["area"] = float(res[0])
                    rec["perimeter"] = float(res[1])
                    rd = float(res[2])
                    if rd > 1e-9:      # 不要用 0 覆盖 UF 已经给出的半径
                        rec["radius_diameter"] = rd
                        rec["is_radius"] = is_radius
                    try:
                        rec["cog"] = point_xyz(res[3])
                    except Exception:
                        pass
                except Exception as exc:
                    diagnostics["sections"].setdefault("face_props", "warn: %r" % (exc,))

                try:
                    box = meas.GetBoundingBoxProperties([face], 0, NXOpen.Point3d(0.0, 0.0, 0.0), False)
                    rec["bbox"] = bbox_from_points([point_xyz(pt) for pt in box[0]])
                except Exception:
                    pass

            try:
                rec["edge_count"] = len(list(face.GetEdges()))
            except Exception:
                pass

            if ctf is not None:
                rec["cog"] = _apply_point(rec["cog"], ctf)
                rec["bbox"] = _apply_bbox(rec["bbox"], ctf)
                rec["point"] = _apply_point(rec["point"], ctf)
                rec["normal"] = _apply_dir(rec["normal"], ctf)
                rec["axis"] = _apply_dir(rec["axis"], ctf)

            tag2face[tag] = face_id
            _used_face_ids.append(face_id)
            model["faces"].append(rec)
            n_faces += 1

        p["face_count"] = len(faces)

        # 边 + 邻接
        if collect_edges:
            try:
                edges = list(body.GetEdges())
            except Exception:
                edges = []
            p["edge_count"] = len(edges)
            for edge in edges:
                edge_seq += 1
                try:
                    etag = int(edge.Tag)
                except Exception:
                    etag = edge_seq
                erec = {
                    "edge_id": "E%d" % etag,
                    "part_id": part_id,
                    "tag": etag,
                    "curve_type": "unknown",
                    "uf_edge_type": 0,
                    "length": None,
                    "bbox": None,
                    "face_ids": [],
                }
                # 长度
                try:
                    erec["length"] = float(edge.GetLength())
                except Exception:
                    pass
                # 曲线类型：优先 NXOpen 枚举名，退化到 UF 码
                try:
                    etype = edge.SolidEdgeType
                    name = None
                    for attr in ("Name", "ToString"):
                        v = getattr(etype, attr, None)
                        if callable(v):
                            try:
                                v = v()
                            except Exception:
                                v = None
                        if isinstance(v, str) and v and "<" not in v:
                            name = v
                            break
                    if name:
                        erec["curve_type"] = name.strip().lower()
                except Exception:
                    pass
                if erec["curve_type"] == "unknown":
                    try:
                        ufcode = int(ufs.Modeling.AskEdgeType(etag))
                        erec["uf_edge_type"] = ufcode
                        erec["curve_type"] = UF_EDGE_TYPES.get(ufcode, "uf_%d" % ufcode)
                    except Exception:
                        pass
                try:
                    efaces = [tag2face.get(int(f.Tag), "") for f in edge.GetFaces()]
                    efaces = [x for x in efaces if x]
                    erec["face_ids"] = efaces
                    if len(efaces) == 2:
                        model["adjacency"].append([efaces[0], efaces[1]])
                except Exception:
                    pass
                model["edges"].append(erec)

        model["parts"].append(p)
        session.ListingWindow.WriteLine("[nxdrp] body %s: %d faces" % (part_id, len(faces)))

    # ---------------- 装配结构 ----------------
    if collect_assembly:
        try:
            comp_asm = part.ComponentAssembly
            root = comp_asm.RootComponent
            if root is not None:
                stack = [(root, "")]
                occ_seq = 0
                guard = 0
                while stack and guard < 5000:
                    guard += 1
                    comp, parent_id = stack.pop()
                    for child in list(comp.GetChildren()):
                        occ_seq += 1
                        occ_id = "O%04d" % occ_seq
                        rec = {
                            "occurrence_id": occ_id,
                            "name": "",
                            "part_ref": "",
                            "parent": parent_id,
                            "transform": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                            "bbox": None,
                            "transform_source": "none",
                        }
                        try:
                            rec["name"] = child.Name or ""
                        except Exception:
                            pass
                        try:
                            rec["part_ref"] = child.Prototype.OwningPart.Leaf or ""
                        except Exception:
                            pass
                        # 不同 NX 版本取变换矩阵的接口不一样，逐个试
                        mat = None
                        if "component_attrs" not in diagnostics:
                            try:
                                diagnostics["component_attrs"] = [
                                    a for a in dir(child) if not a.startswith("_")]
                            except Exception:
                                pass
                        for getter in (lambda c: c.Transform,
                                       lambda c: c.GetTransform(),
                                       lambda c: c.GetPositionOrientation(),
                                       lambda c: ufs.Assem.AskComponentTransform(c.Tag)):
                            try:
                                mat = getter(child)
                                rec["transform_source"] = "property"
                                break
                            except Exception:
                                continue
                        if mat is not None:
                            try:
                                xs = getattr(mat, "Xx", None)
                                if isinstance(xs, (int, float)):
                                    rec["transform"] = [
                                        [float(mat.Xx), float(mat.Xy), float(mat.Xz), float(mat.Xt)],
                                        [float(mat.Yx), float(mat.Yy), float(mat.Yz), float(mat.Yt)],
                                        [float(mat.Zx), float(mat.Zy), float(mat.Zz), float(mat.Zt)],
                                        [0.0, 0.0, 0.0, 1.0],
                                    ]
                                    rec["transform_source"] = "matrix3x4"
                            except Exception as exc:
                                diagnostics["warnings"].append("transform: %r" % (exc,))
                        if rec["transform_source"] == "none":
                            try:
                                pos_obj = child.GetPosition()
                                # 这个版本返回元组 (location, orientation)，不是对象
                                if isinstance(pos_obj, (tuple, list)):
                                    loc = pos_obj[0] if len(pos_obj) > 0 else None
                                    ori = pos_obj[1] if len(pos_obj) > 1 else None
                                else:
                                    loc = getattr(pos_obj, "Location", None)
                                    ori = getattr(pos_obj, "Orientation", None)
                                if loc is not None:
                                    o = ori if ori is not None else None
                                    rec["transform"] = [
                                        [float(getattr(o, "Xx", 1.0)), float(getattr(o, "Xy", 0.0)),
                                         float(getattr(o, "Xz", 0.0)), float(loc.X)],
                                        [float(getattr(o, "Yx", 0.0)), float(getattr(o, "Yy", 1.0)),
                                         float(getattr(o, "Yz", 0.0)), float(loc.Y)],
                                        [float(getattr(o, "Zx", 0.0)), float(getattr(o, "Zy", 0.0)),
                                         float(getattr(o, "Zz", 1.0)), float(loc.Z)],
                                        [0.0, 0.0, 0.0, 1.0],
                                    ]
                                    rec["transform_source"] = "GetPosition"
                            except Exception as exc:
                                diagnostics["warnings"].append("placement: %r" % (exc,))
                        model["occurrences"].append(rec)
                        stack.append((child, occ_id))
        except Exception as exc:
            diagnostics["sections"]["assembly"] = "warn: %r" % (exc,)

    # ---------------- 收尾 ----------------
    model["meta"]["has_normals"] = any(f.get("normal") for f in model["faces"])
    model["meta"]["has_axes"] = any(f.get("axis") for f in model["faces"])
    model["meta"]["journal_face_type_map"] = {str(k): v for k, v in FACE_TYPE_MAP.items()}
    diagnostics["counts"] = {
        "bodies": n_bodies,
        "faces": len(model["faces"]),
        "edges": len(model["edges"]),
        "occurrences": len(model["occurrences"]),
        "adjacency_pairs": len(model["adjacency"]),
    }
    if UNKNOWN_CODES:
        diagnostics["warnings"].append("未识别的 SolidFaceType: %s" % sorted(UNKNOWN_CODES))
    diagnostics["elapsed_s"] = round(time.time() - t0, 2)
    model["diagnostics"] = diagnostics

    try:
        part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue,
                   NXOpen.BasePart.CloseModified.CloseModified, None)
    except Exception:
        pass

    emit({"ok": True, "model": model, "diagnostics": diagnostics})
    session.ListingWindow.WriteLine("[nxdrp] done: %d parts / %d faces / %.1fs"
                                    % (len(model["parts"]), len(model["faces"]), time.time() - t0))


try:
    main()
except Exception as exc:
    emit({
        "ok": False,
        "error": "%r" % (exc,),
        "traceback": traceback.format_exc(),
        "diagnostics": {"journal": "extract_geometry", "stage": "main"},
    })
