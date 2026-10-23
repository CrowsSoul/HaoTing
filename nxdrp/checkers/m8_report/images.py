"""离线三维定位渲染。支持 STL 三角网格或如实标注的包围盒示意。"""
from __future__ import annotations
import math
import struct
import hashlib
from pathlib import Path
from .core import bbox, vec


def font(size):
    from PIL import ImageFont
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def corners(b):
    return [(b["x"+x], b["y"+y], b["z"+z])
            for x in ("min", "max") for y in ("min", "max") for z in ("min", "max")]


def read_stl(path):
    data = Path(path).read_bytes()
    triangles = []
    if len(data) >= 84 and 84 + struct.unpack_from("<I", data, 80)[0]*50 == len(data):
        n = struct.unpack_from("<I", data, 80)[0]
        if n > 120000:
            raise ValueError("STL 面数超过 120000，请先简化网格")
        for i in range(n):
            raw = struct.unpack_from("<9f", data, 84+i*50+12)
            triangles.append([raw[0:3], raw[3:6], raw[6:9]])
    else:
        points = []
        for line in data.decode("ascii").splitlines():
            fields = line.split()
            if fields and fields[0] == "vertex":
                points.append(tuple(map(float, fields[1:4])))
        if len(points) % 3 or len(points) > 360000:
            raise ValueError("STL 顶点数量无效或过多")
        triangles = [points[i:i+3] for i in range(0, len(points), 3)]
    if not triangles or not all(vec(p) for t in triangles for p in t):
        raise ValueError("STL 为空或包含无效坐标")
    return triangles


def render_position(finding, model, output, triangles=None):
    from PIL import Image, ImageDraw
    W, H = 1200, 750
    image = Image.new("RGB", (W, H), "#f3f6fa")
    draw = ImageDraw.Draw(image)
    # 同一视角下绘制几何、问题标记和路径，原始模型坐标保持不变。
    right, up, depth = (0.8, 0.6, 0), (-0.3, 0.4, 0.8660254), (0.5196, -0.6928, 0.5)
    dot = lambda p, a: sum(p[i]*a[i] for i in range(3))
    boxes = [(p.get("part_id", ""), p["bbox"]) for p in model.get("parts", []) if bbox(p.get("bbox"))]
    points = [p for t in triangles for p in t] if triangles else [p for _, b in boxes for p in corners(b)]
    if finding.get("bbox"):
        points.extend(corners(finding["bbox"]))
    if finding.get("position"):
        points.append(finding["position"])
    points += finding["source"].get("path_points", [])
    if not points:
        draw.text((60, 330), "缺少几何与坐标，请检测模块补充位置", font=font(26), fill="#7b3540")
        image.save(output)
        return
    xs, ys = [dot(p, right) for p in points], [dot(p, up) for p in points]
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    scale = min(1000/max(max(xs)-min(xs), 1), 490/max(max(ys)-min(ys), 1))
    project = lambda p: (600+(dot(p, right)-cx)*scale, 400-(dot(p, up)-cy)*scale)
    if triangles:
        import numpy as np
        # 深度缓冲处理孔腔遮挡，避免按面中心排序将腔体错误覆盖。
        pixels = np.asarray(image).copy()
        zbuffer = np.full((H, W), -np.inf)
        for t in triangles:
            a = [t[1][i]-t[0][i] for i in range(3)]
            b = [t[2][i]-t[0][i] for i in range(3)]
            n = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
            length = math.sqrt(sum(x*x for x in n)) or 1
            light = 0.55+0.4*abs(dot(n, (0.3, -0.5, 0.812))/length)
            color = tuple(int(c*min(light, 1)) for c in (132, 171, 199))
            projected = [project(p) for p in t]
            x0 = max(0, int(math.floor(min(p[0] for p in projected))))
            x1 = min(W-1, int(math.ceil(max(p[0] for p in projected))))
            y0 = max(0, int(math.floor(min(p[1] for p in projected))))
            y1 = min(H-1, int(math.ceil(max(p[1] for p in projected))))
            if x1 <= x0 or y1 <= y0:
                continue
            (ax, ay), (bx, by), (cxp, cyp) = projected
            denominator = (by-cyp)*(ax-cxp)+(cxp-bx)*(ay-cyp)
            if abs(denominator) < 1e-10:
                continue
            yy, xx = np.mgrid[y0:y1+1, x0:x1+1]
            xx, yy = xx+.5, yy+.5
            wa = ((by-cyp)*(xx-cxp)+(cxp-bx)*(yy-cyp))/denominator
            wb = ((cyp-ay)*(xx-cxp)+(ax-cxp)*(yy-cyp))/denominator
            wc = 1-wa-wb
            z = wa*dot(t[0], depth)+wb*dot(t[1], depth)+wc*dot(t[2], depth)
            window = zbuffer[y0:y1+1, x0:x1+1]
            mask = (wa>=-1e-8)&(wb>=-1e-8)&(wc>=-1e-8)&(z>window)
            window[mask] = z[mask]
            pixels[y0:y1+1, x0:x1+1][mask] = color
        image = Image.fromarray(pixels)
        draw = ImageDraw.Draw(image)
    else:
        for pid, box in boxes:
            pts = corners(box)
            draw.polygon([project(pts[i]) for i in (0, 2, 6, 4)], fill="#e1eaf2")
            for i in range(8):
                for j in range(i+1, 8):
                    if (i ^ j) in (1, 2, 4):
                        draw.line([project(pts[i]), project(pts[j])], fill="#93a7ba", width=2)
            draw.text(project(pts[3]), pid, font=font(18), fill="#46647b")
    if finding.get("bbox"):
        pts = corners(finding["bbox"])
        for i in range(8):
            for j in range(i+1, 8):
                if (i ^ j) in (1, 2, 4):
                    draw.line([project(pts[i]), project(pts[j])], fill="#d15a38", width=3)
    path = finding["source"].get("path_points", [])
    if len(path) > 1:
        draw.line([project(p) for p in path], fill="#e4a62c", width=5)
    if finding.get("position"):
        x, y = project(finding["position"])
        draw.ellipse((x-9, y-9, x+9, y+9), fill="#cf4b32", outline="white", width=2)
        # 标签固定在画布内，避免边缘裁切。
        tx, ty = min(max(x+22, 30), 870), min(max(y-45, 145), 610)
        draw.line([(x, y), (tx, ty+14)], fill="#cf4b32", width=2)
        draw.text((tx, ty), finding["finding_id"][:38], font=font(20), fill="#a93d27")
    label = "STL 网格三维定位图" if triangles else "几何包围盒定位示意  非 NX 截图"
    draw.text((40, 30), label, font=font(27), fill="#203e54")
    draw.text((40, 75), "红色点为问题位置，橙框为问题范围，金色线为路径", font=font(18), fill="#61778a")
    draw.text((40, 696), f"模型 {str(model.get('model_id', '未附模型'))[:50]}   坐标单位 {model.get('units', '未提供')}", font=font(18), fill="#61778a")
    image.save(output)


def attach_images(report, model, directory, screenshots=None, mesh=None):
    from PIL import Image
    screenshots = screenshots or {}
    unknown = set(screenshots) - {f["finding_id"] for f in report["findings"]}
    if unknown:
        raise ValueError(f"截图映射包含未知问题编号：{sorted(unknown)}")
    directory = Path(directory)
    directory.mkdir()
    triangles = read_stl(mesh) if mesh else None
    mesh_digest = hashlib.sha256(Path(mesh).read_bytes()).hexdigest() if mesh else None
    if triangles and not model:
        raise ValueError("使用 STL 需同时附上同坐标系的模型 JSON")
    for f in report["findings"]:
        filename = f["anchor"]+".png"
        out = directory / filename
        if f["finding_id"] in screenshots:
            src = Path(screenshots[f["finding_id"]])
            with Image.open(src) as img:
                if img.width*img.height > 40000000:
                    raise ValueError("截图尺寸过大")
                img.convert("RGB").save(out)
            f["image_kind"] = "真实三维截图"
            f["image_source"] = src.name
            provenance = {"method": "submitted_image", "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                          "content_confirmation": "提交者负责确认截图对应同一模型与问题，M8 不验证图像语义"}
        else:
            render_position(f, model or {}, out, triangles)
            f["image_kind"] = "网格三维定位图" if triangles else "包围盒定位示意"
            f["image_source"] = Path(mesh).name if mesh else "模型及问题几何数据"
            provenance = {"method": "stl_zbuffer" if triangles else "bbox_projection", "mesh_sha256": mesh_digest,
                          "view_direction": [0.5196, -0.6928, 0.5], "projection": "orthographic",
                          "content_confirmation": "STL 与模型的同坐标系关联由提交者确认；图中标记为问题坐标和包围盒"}
        f["image"] = "images/"+filename
        f["image_evidence"] = {**provenance, "finding_id": f['finding_id'], "check_item_id": f['check_item_id'],
                               "model_id": report['model_id'], "model_sha256": report['model_digest'],
                               "position": f['position'], "bbox": f['bbox'],
                               "coordinate_units": f.get('coordinate_units', '未提供'),
                               "face_ids": f['source']['evidence'].get('face_ids', []),
                               "image": f['image'], "image_sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
