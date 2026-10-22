# -*- coding: utf-8 -*-
"""从 catalog.py 生成规则库骨架。

规则库是「数据」，checker 是「算法」。新增检查项时先跑这个脚本拿到一条空规则，
填上 params，再写 checker —— 顺序反过来会导致阈值散落在代码里，违反合同第 7 条
（工程师要能免编程维护规则）。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp import catalog  # noqa: E402
from nxdrp.contracts import Rule, RuleBook  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_DIR = os.path.join(ROOT, "rules")

#: 默认严重度：安全与干涉最高，其余按提示级别起步，由工艺工程师后续调整
SEVERITY_OVERRIDE = {
    "SAF-01": "P0",
    "SAF-02": "P0",
    "SAF-03": "P1",
    "DFM-01": "P1",
    "DFM-05": "P1",
    "DFM-08": "P1",
    "DFM-13": "P1",
    "DFM-27": "P2",
}

#: 每个检查项的参数骨架（键名先占位，值由工艺工程师按甲方标准填写）
PARAM_SKELETON = {
    "DFM-01": {"interference_volume_mm3": 0.01, "critical_gap_mm": 0.05, "ignore_face_area_below_mm2": 0.1},
    "DFM-02": {"min_clearance_mm": 0.3},
    "DFM-05": {"tool_envelope_diameter_mm": 10.0, "tool_envelope_height_mm": 40.0},
    "DFM-06": {"axial_clearance_mm": 0.5, "radial_clearance_mm": 0.5},
    "DFM-07": {"engagement_ratio_steel": 1.0, "engagement_ratio_plastic": 1.5},
    "DFM-08": {"material": "PA66", "min_wall_thickness_mm": 0.8},
    "DFM-09": {"uniform_ratio_low": 0.8, "uniform_ratio_high": 1.25, "max_area_ratio": 0.1},
    "DFM-13": {"pull_direction": [0, 0, 1], "min_draft_angle_deg": 0.5},
    "DFM-16": {"inner_radius_ratio": 0.25, "outer_radius_ratio": 0.5},
    "DFM-18": {"sharp_angle_deg": 60.0},
    "DFM-19": {"min_bend_radius_ratio": 0.5, "sheet_thickness_mm": 1.0},
    "DFM-20": {"min_edge_distance_ratio": 1.5},
    "DFM-21": {"min_hole_spacing_ratio": 2.0},
    "DFM-22": {"min_hole_diameter_ratio": 1.0},
    "DFM-23": {"min_slot_width_ratio": 1.2},
    "DFM-25": {"min_flange_height_ratio": 3.0},
    "DFM-27": {"deep_hole_ratio": 4.0, "very_deep_hole_ratio": 10.0},
    "DFM-28": {"deep_slot_ratio": 3.0},
    "DFM-31": {
        "standard_diameters": [1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0,
                               6.5, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0, 16.0, 18.0, 20.0],
        "tolerance_mm": 0.05,
        "max_hole_diameter_mm": 20.0,
    },
    "DFM-32": {"max_distinct_radii": 3, "cluster_tolerance_mm": 0.1},
    "DFM-33": {"min_top_fillet_mm": 0.5},
    "DFM-34": {"standard_chamfer_deg": 45.0, "standard_chamfer_mm": 0.5},
    "DFM-36": {"standard_angles_deg": [0, 30, 45, 60, 90]},
    "SAF-01": {"rated_voltage_v": 400, "pollution_degree": 2, "material_group": "II", "overvoltage_category": "III"},
    "SAF-02": {"rated_voltage_v": 400, "pollution_degree": 2, "material_group": "II", "cti": 600},
    "SAF-TOOL": {"tool": "AutoCrear", "tool_exe": "", "tool_timeout_s": 600, "result_format": "auto"},
    "SAF-03": {"combine": "worst"},
    "SAF-04": {"target_margin_mm": 0.5},
    "PERF-01": {"current_a": 16.0, "ambient_temp_c": 25.0, "interval_confidence": 0.8},
}


def build() -> RuleBook:
    rules = []
    for item in catalog.CATALOG:
        rules.append(
            Rule(
                rule_id=f"R-{item.check_item_id}",
                check_item_id=item.check_item_id,
                process_type=item.process_type,
                name=item.name_cn,
                enabled=True,
                params=PARAM_SKELETON.get(item.check_item_id, {}),
                version="0.1",
                source_standard="",
                severity=SEVERITY_OVERRIDE.get(item.check_item_id, "P2"),
                notes=item.hint,
                owner=f"{item.owner_module}",
            )
        )
    return RuleBook(
        name="dfm_default",
        version="0.1",
        updated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        rules=rules,
    )


def main():
    os.makedirs(RULES_DIR, exist_ok=True)
    book = build()
    path = os.path.join(RULES_DIR, "dfm_default.json")
    book.save(path)
    book.validate()
    print(f"已生成 {path}")
    print(f"  规则条数: {len(book.rules)}")
    for mod, items in sorted(
        ((m, [i for i in catalog.CATALOG if i.owner_module == m]) for m in {i.owner_module for i in catalog.CATALOG})
    ):
        print(f"  {mod}: {len(items)} 项")


if __name__ == "__main__":
    main()
