# -*- coding: utf-8 -*-
"""把 NX 导出的 STL 渲染成示意图。

几何来自 NX（`journals/export_stl_v2.py` 导出），这里只做投影与着色：
正交投影 + 平面着色 + 画家算法 + 2 倍超采样。

用法：python -m tools.render_models
产出：mockdata/_shots/*.png
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "mockdata", "_shots")
MODELS = os.path.join(ROOT, "mockdata", "models")

#: 视角：从右前上方看
VIEW = (0.85, -1.15, 0.72)
LIGHT = (-0.55, -0.95, 0.62)

BASE = np.array([0.62, 0.72, 0.85])       # 主体蓝灰
BASE_B = np.array([0.46, 0.58, 0.74])     # 相邻组件用的深一档，便于分辨边界
EDGE_MUL = 0.90
BG = (255, 255, 255)
FRAME = (223, 230, 240)
EDGE = (42, 62, 92)

SS = 2                                     # 超采样倍数


def load_stl(path: str) -> np.ndarray:
    """读二进制 STL，返回 (n, 3, 3)。"""
    with open(path, "rb") as fh:
        fh.read(80)
        (count,) = struct.unpack("<I", fh.read(4))
        raw = fh.read(count * 50)
    data = np.frombuffer(raw, dtype=np.uint8).reshape(count, 50)
    tri = data[:, 12:48].copy().view("<f4").reshape(count, 3, 3).astype(np.float64)
    return tri


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def transform(tri: np.ndarray, m: list | None) -> np.ndarray:
    if m is None:
        return tri
    M = np.array(m, dtype=np.float64)
    R, t = M[:3, :3], M[:3, 3]
    return tri @ R.T + t


def render(tris: np.ndarray, groups: np.ndarray | None = None,
           size=(1600, 1120), margin=0.08, view=None) -> Image.Image:
    d = unit(view or VIEW)
    up0 = np.array([0.0, 0.0, 1.0])
    right = unit(np.cross(up0, d))
    up = np.cross(d, right)

    flat = tris.reshape(-1, 3)
    px = flat @ right
    py = flat @ up
    pz = flat @ d

    x0, x1 = px.min(), px.max()
    y0, y1 = py.min(), py.max()
    W, H = size[0] * SS, size[1] * SS
    span = max(x1 - x0, y1 - y0) * (1 + 2 * margin)
    scale = min(W, H) / span
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    sx = (px - cx) * scale + W / 2
    sy = H / 2 - (py - cy) * scale

    P = np.stack([sx, sy], axis=1).reshape(-1, 3, 2)
    D = pz.reshape(-1, 3).mean(axis=1)

    # 法向与着色
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    nrm = np.cross(b - a, c - a)
    ln = np.linalg.norm(nrm, axis=1)
    ln[ln < 1e-12] = 1.0
    nrm = nrm / ln[:, None]

    facing = nrm @ d
    keep = facing < 0                      # 背面剔除
    intensity = 0.58 + 0.42 * np.clip(nrm @ unit(LIGHT), 0, 1)
    base = BASE[None, :].repeat(len(tris), axis=0)
    if groups is not None:
        base[groups % 2 == 1] = BASE_B
    # 深度雾化：凹腔的底面与顶面法向相同，不加距离衰减会连成一片
    dmin, dmax = D.min(), D.max()
    fog = 1.0 - 0.26 * (D - dmin) / (dmax - dmin) if dmax > dmin else np.ones_like(D)
    shade = np.clip(base * intensity[:, None] * fog[:, None], 0, 1)
    colors = (shade * 255).astype(np.uint8)

    # ---- z-buffer 光栅化（画家算法在凹形零件上会把腔体盖住）----
    zbuf = np.full((H, W), np.inf, dtype=np.float64)
    buf = np.zeros((H, W, 3), dtype=np.uint8)
    buf[:, :] = BG

    Dv = pz.reshape(-1, 3)                 # 每个顶点的视深

    for i in range(len(tris)):
        if not keep[i]:
            continue
        p = P[i]
        x0 = max(int(np.floor(p[:, 0].min())), 0)
        x1 = min(int(np.ceil(p[:, 0].max())), W - 1)
        y0 = max(int(np.floor(p[:, 1].min())), 0)
        y1 = min(int(np.ceil(p[:, 1].max())), H - 1)
        if x1 <= x0 or y1 <= y0:
            continue

        (ax, ay), (bx, by), (cx, cy) = p[0], p[1], p[2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue

        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                             np.arange(y0, y1 + 1) + 0.5)
        l1 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        l2 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
        if not inside.any():
            continue

        d = l1 * Dv[i][0] + l2 * Dv[i][1] + l3 * Dv[i][2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        mask = inside & (d < sub)
        if not mask.any():
            continue
        sub[mask] = d[mask]
        tile = buf[y0:y1 + 1, x0:x1 + 1]
        tile[mask] = colors[i]

    img = Image.fromarray(buf, "RGB")
    draw = ImageDraw.Draw(img)

    # ---- 结构线：按顶点 id 配对，只画相邻面夹角明显的边 ----
    verts = np.round(tris.reshape(-1, 3), 2)
    uniq, inv = np.unique(verts, axis=0, return_inverse=True)
    vid = inv.reshape(-1, 3)

    edge_normals = {}
    edge_seg = {}
    for i in range(len(tris)):
        if not keep[i]:
            continue
        for a, b in ((0, 1), (1, 2), (2, 0)):
            ka, kb = int(vid[i][a]), int(vid[i][b])
            key = (ka, kb) if ka <= kb else (kb, ka)
            edge_normals.setdefault(key, []).append(nrm[i])
            edge_seg[key] = (P[i][a], P[i][b])
            edge_seg.setdefault("__depth__", {})[key] = (Dv[i][a], Dv[i][b])

    Dv_of = edge_seg.pop("__depth__", {})
    tol = (dmax - dmin) * 0.02 if dmax > dmin else 1.0
    for key, norms in edge_normals.items():
        if len(norms) == 2 and float(norms[0] @ norms[1]) > 0.92:
            continue
        seg = edge_seg[key]
        (x1, y1), (x2, y2) = seg[0], seg[1]
        # 用中点做深度测试：被前面的面挡住的边不画
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        ix, iy = int(round(mx)), int(round(my))
        if not (0 <= ix < W and 0 <= iy < H):
            continue
        edge_depth = 0.5 * (Dv_of[key][0] + Dv_of[key][1])
        if edge_depth > zbuf[iy, ix] + tol:
            continue
        draw.line([(x1, y1), (x2, y2)], fill=EDGE, width=max(1, SS))

    return autocrop(img, pad=42)


def autocrop(img: Image.Image, pad: int = 40) -> Image.Image:
    """按内容裁边，再补一圈留白，让图在文档里更紧凑。"""
    arr = np.asarray(img.convert("RGB")).astype(np.int16)
    mask = np.abs(arr - np.array(BG, dtype=np.int16)).sum(axis=2) > 12
    if not mask.any():
        return img
    ys, xs = np.where(mask)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, img.width)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, img.height)
    out = img.crop((x0, y0, x1, y1))
    # 加一圈浅边框：既是视觉分隔，也遮住部分渲染器的默认细线
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, out.width - 1, out.height - 1], outline=FRAME, width=2)
    return out


def load_occurrences(model_json: str) -> list:
    """从已解析的 ModelBundle 里取组件变换矩阵。"""
    path = os.path.join(MODELS, model_json)
    if not os.path.isfile(path):
        return [None]
    with open(path, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    mats = [o.get("transform") for o in d.get("occurrences", [])]
    return mats or [None]


def main():
    os.makedirs(SHOTS, exist_ok=True)
    stl = os.path.join(SHOTS, "port.stl")
    if not os.path.isfile(stl):
        print("缺少 %s，先跑 journals/export_stl_v2" % stl)
        return 1

    jobs = [
        ("single", "单件（Pressure Port 几何）", "port.stl", [None]),
        ("asm_test", "两组件装配", "port.stl", load_occurrences("asm_test.model.json")),
        ("demo_asm", "六组件混合场景", "port.stl", load_occurrences("demo_asm.model.json")),
        ("demo_normal", "五组件纯负样本场景", "port.stl", load_occurrences("demo_normal.model.json")),
        ("demo_edge", "四组件阈值边界场景", "port.stl", load_occurrences("demo_edge.model.json")),
        ("demo_large", "二十四组件压测场景", "port.stl", load_occurrences("demo_large.model.json")),
        # 四类缺陷件：每类几何不同，各用各的 STL
        ("plate_holes", "四个非标孔板件", "plate_holes.stl", [None]),
        ("thin_wall", "薄壁壳体", "thin_wall.stl", [None]),
        ("deep_slot", "窄深槽块", "deep_slot.stl", [None]),
        ("bosses", "带圆柱凸台的底板", "bosses.stl", [None]),
    ]

    cache = {}
    for job in jobs:
        key, label, stl_name, mats = job[0], job[1], job[2], job[3]
        cam = job[4] if len(job) > 4 else None
        if stl_name not in cache:
            cache[stl_name] = load_stl(os.path.join(SHOTS, stl_name))
            print("  %-20s %d 个三角面片" % (stl_name, len(cache[stl_name])))
        one = cache[stl_name]
        parts = [transform(one, m) for m in mats]
        tris = np.concatenate(parts, axis=0)
        groups = np.repeat(np.arange(len(parts)), len(one))
        img = render(tris, groups, view=cam)
        out = os.path.join(SHOTS, key + ".png")
        img.save(out)
        print("  %-12s %4d 个实例  %6d 面  -> %s" % (key, len(mats), len(tris), os.path.basename(out)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
