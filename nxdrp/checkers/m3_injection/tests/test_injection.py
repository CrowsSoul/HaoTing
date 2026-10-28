# -*- coding: utf-8 -*-
"""M3 注塑 / 铸造检查项：正例、负例、阈值边界。"""

import math
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
sys.path.insert(0, ROOT)

from nxdrp.checkers.base import CheckContext  # noqa: E402
from nxdrp.checkers.m3_injection.dfm08_min_wall import MinWallThicknessChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm09_uniform_wall import UniformWallThicknessChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm10_wall_variation import WallVariationChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm11_rib_design import RibDesignChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm12_mold_wall import MoldWallThicknessChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm13_draft_angle import DraftAngleChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm14_undercut import UndercutChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm15_boss_design import BossDesignChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm16_fillet_radius import FilletRadiusChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm17_multi_pull import MultiPullDirectionChecker  # noqa: E402
from nxdrp.checkers.m3_injection.dfm18_sharp_corner import SharpCornerChecker  # noqa: E402
from nxdrp.contracts import BBox, Edge, Face, ModelBundle, Part, Rule, RuleBook  # noqa: E402
from nxdrp.pipeline import run as run_pipeline  # noqa: E402
from nxdrp.registry import discover  # noqa: E402


BOX = BBox(0.0, 0.0, 0.0, 20.0, 20.0, 10.0)
RULEBOOK = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))


def make_face(
    fid,
    *,
    normal=(0.0, 0.0, 1.0),
    cog=(10.0, 10.0, 0.0),
    area=400.0,
    bbox=None,
    kind="planar",
    radius=None,
):
    return Face(
        face_id=fid,
        part_id="P01",
        solid_face_type=kind,
        point=cog,
        normal=normal if kind == "planar" else None,
        axis=(0.0, 0.0, 1.0) if kind != "planar" else None,
        area=area,
        perimeter=80.0,
        radius_diameter=radius,
        is_radius=True,
        cog=cog,
        bbox=bbox or BBox(cog[0], cog[1], cog[2], cog[0], cog[1], cog[2]),
    )


def make_model(faces=None, edges=None, adjacency=None, meta=None, material="PA66"):
    model = ModelBundle(model_id="m3-test", units="mm")
    model.parts.append(
        Part(
            part_id="P01",
            name="TEST PART",
            material=material,
            body_type="solid",
            bbox=BOX,
            face_count=len(faces or []),
            edge_count=len(edges or []),
        )
    )
    model.faces.extend(faces or [make_face("F1")])
    model.edges.extend(edges or [])
    model.adjacency.extend(adjacency or [])
    model.meta["m3_features"] = meta or {}
    model.validate()
    return model


def run(checker, model, params=None):
    base_rule = RULEBOOK.get(checker.check_item_id)
    rule_params = dict(base_rule.params) if base_rule else {}
    rule_params.update(params or {})
    effective = checker.merged_params(rule_params)
    rule = Rule(
        rule_id=f"test-{checker.check_item_id}",
        check_item_id=checker.check_item_id,
        params=rule_params,
        severity=base_rule.severity if base_rule else "P2",
    )
    ctx = CheckContext(model=model, rule=rule, params=effective, checker=checker)
    return list(checker.check(ctx) or [])


def wall_pair(thickness):
    return [
        make_face("F1", normal=(0.0, 0.0, -1.0), cog=(10.0, 10.0, 0.0), bbox=BOX),
        make_face("F2", normal=(0.0, 0.0, 1.0), cog=(10.0, 10.0, thickness), bbox=BOX),
    ]


class TestRegistrationAndRules(unittest.TestCase):
    def test_all_m3_ids_registered(self):
        registry = discover()
        self.assertEqual(len(registry.errors), 0, [e.message for e in registry.errors])
        for number in range(8, 19):
            self.assertIn(f"DFM-{number:02d}", registry.ids())

    def test_rulebook_valid_and_m3_complete(self):
        RULEBOOK.validate()
        for number in range(8, 19):
            self.assertIsNotNone(RULEBOOK.get(f"DFM-{number:02d}"))

    def test_m3_rule_sources_are_documented(self):
        for number in range(8, 19):
            rule = RULEBOOK.get(f"DFM-{number:02d}")
            self.assertTrue(rule.source_standard, f"{rule.check_item_id} 缺少阈值依据")

    def test_cli_default_rulebook_has_no_errors(self):
        model = ModelBundle.load(os.path.join(ROOT, "mockdata", "models", "demo_normal.model.json"))
        only = [f"DFM-{number:02d}" for number in range(8, 19)]
        result = run_pipeline(model, RuleBook(), discover(), only=only)
        self.assertFalse(
            [r for r in result.results if r.status == "error"],
            [(r.check_item_id, r.reason) for r in result.results if r.status == "error"],
        )


class TestDfm08MinWall(unittest.TestCase):
    def test_reports_below_material_minimum(self):
        model = make_model(wall_pair(0.5), material="PA66")
        self.assertEqual(len(run(MinWallThicknessChecker(), model)), 1)

    def test_does_not_report_at_minimum(self):
        model = make_model(wall_pair(0.8), material="PA66")
        self.assertEqual(run(MinWallThicknessChecker(), model), [])

    def test_uses_material_specific_threshold(self):
        model = make_model(wall_pair(1.2), material="PC")
        found = run(MinWallThicknessChecker(), model)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].threshold_value, 1.5)


class TestDfm09UniformWall(unittest.TestCase):
    def _records(self, values):
        return {
            "wall_samples": [
                {
                    "part_id": "P01",
                    "thickness_mm": value,
                    "area_mm2": 100.0,
                    "face_ids": [f"F{i + 1}"],
                    "location": [float(i), 0.0, 0.0],
                }
                for i, value in enumerate(values)
            ]
        }

    def test_reports_excess_deviation_area(self):
        model = make_model(meta=self._records([2.0, 2.0, 2.8]))
        found = run(UniformWallThicknessChecker(), model, {"nominal_wall_thickness_mm": 2.0})
        self.assertEqual(len(found), 1)

    def test_boundary_ratio_is_accepted(self):
        model = make_model(meta=self._records([2.0, 2.0, 2.5]))
        found = run(UniformWallThicknessChecker(), model, {"nominal_wall_thickness_mm": 2.0})
        self.assertEqual(found, [])

    def test_deviation_area_ratio_below_limit_is_accepted(self):
        values = [2.0] * 9 + [3.0]
        model = make_model(meta=self._records(values))
        records = model.meta["m3_features"]["wall_samples"]
        for i, rec in enumerate(records):
            rec["area_mm2"] = 0.5 if i == 9 else 10.0
        found = run(UniformWallThicknessChecker(), model, {"nominal_wall_thickness_mm": 2.0})
        self.assertEqual(found, [])


class TestDfm10WallVariation(unittest.TestCase):
    def _model(self, thickness_b):
        return make_model(
            meta={
                "wall_samples": [
                    {
                        "part_id": "P01",
                        "thickness_mm": 2.0,
                        "face_ids": ["F1"],
                        "adjacent_face_ids": ["F2"],
                    },
                    {
                        "part_id": "P01",
                        "thickness_mm": thickness_b,
                        "face_ids": ["F2"],
                    },
                ]
            }
        )

    def test_reports_excess_gradient(self):
        self.assertEqual(len(run(WallVariationChecker(), self._model(3.0))), 1)

    def test_boundary_gradient_is_accepted(self):
        found = run(WallVariationChecker(), self._model(3.0), {"max_gradient_ratio": 1.0 / 3.0})
        self.assertEqual(found, [])

    def test_small_gradient_is_accepted(self):
        self.assertEqual(run(WallVariationChecker(), self._model(2.2)), [])


class TestDfm11RibDesign(unittest.TestCase):
    def _model(self, root, height):
        return make_model(
            meta={
                "ribs": [
                    {
                        "part_id": "P01",
                        "root_thickness_mm": root,
                        "height_mm": height,
                        "face_ids": ["F1"],
                        "location": [5.0, 5.0, 2.0],
                        "origin": "upstream_feature",
                    }
                ]
            }
        )

    def test_reports_thick_rib_root(self):
        found = run(RibDesignChecker(), self._model(1.4, 5.0), {"nominal_wall_thickness_mm": 2.0})
        self.assertEqual(len(found), 1)

    def test_root_ratio_boundary_is_accepted(self):
        found = run(RibDesignChecker(), self._model(1.2, 5.0), {"nominal_wall_thickness_mm": 2.0})
        self.assertEqual(found, [])

    def test_reports_excessive_rib_height(self):
        found = run(RibDesignChecker(), self._model(1.0, 5.1), {"nominal_wall_thickness_mm": 2.0})
        self.assertEqual(len(found), 1)


class TestDfm12MoldWall(unittest.TestCase):
    def _model(self, x2):
        return make_model(
            meta={
                "ribs": [
                    {"part_id": "P01", "root_thickness_mm": 2.0, "location": [0.0, 5.0, 2.0]},
                    {"part_id": "P01", "root_thickness_mm": 2.0, "location": [x2, 5.0, 2.0]},
                ]
            }
        )

    def test_reports_thin_mold_steel(self):
        self.assertEqual(len(run(MoldWallThicknessChecker(), self._model(4.0))), 1)

    def test_boundary_is_accepted(self):
        self.assertEqual(run(MoldWallThicknessChecker(), self._model(6.0)), [])

    def test_wide_spacing_is_accepted(self):
        self.assertEqual(run(MoldWallThicknessChecker(), self._model(10.0)), [])

    def test_skips_without_two_comparable_features(self):
        checker = MoldWallThicknessChecker()
        ok, reason = checker.applies(make_model(), checker.default_params)
        self.assertFalse(ok)
        self.assertIn("至少两个", reason)


class TestDfm13Draft(unittest.TestCase):
    def _model(self, angle):
        radians = math.radians(angle)
        # 竖直面法向为 +X；拔模角 a 使法向向开模方向倾斜 a。
        face = make_face("F1", normal=(math.cos(radians), 0.0, math.sin(radians)))
        return make_model([face])

    def test_reports_shallow_draft(self):
        self.assertEqual(len(run(DraftAngleChecker(), self._model(0.4))), 1)

    def test_boundary_draft_is_accepted(self):
        self.assertEqual(run(DraftAngleChecker(), self._model(0.5)), [])

    def test_sufficient_draft_is_accepted(self):
        self.assertEqual(run(DraftAngleChecker(), self._model(1.5)), [])


class TestDfm14Undercut(unittest.TestCase):
    def _model(self, **record):
        base = {
            "part_id": "P01",
            "depth_mm": 1.0,
            "direction": [1.0, 0.0, 0.0],
            "face_ids": ["F1"],
            "location": [5.0, 5.0, 2.0],
        }
        base.update(record)
        return make_model(meta={"undercuts": [base]})

    def test_reports_feature_undercut(self):
        checker = UndercutChecker()
        model = self._model()
        self.assertTrue(checker.applies(model, {})[0])
        self.assertEqual(len(run(checker, model)), 1)

    def test_exempt_undercut_is_accepted(self):
        self.assertEqual(run(UndercutChecker(), self._model(exempt=True)), [])

    def test_missing_feature_data_is_skipped(self):
        checker = UndercutChecker()
        ok, reason = checker.applies(make_model(), {})
        self.assertFalse(ok)
        self.assertIn("缺少倒扣特征", reason)


class TestDfm15Boss(unittest.TestCase):
    def _model(self, **record):
        base = {
            "part_id": "P01",
            "outer_radius_mm": 2.0,
            "wall_thickness_mm": 1.0,
            "top_thickness_mm": 1.0,
            "root_fillet_radius_mm": 0.5,
            "side_wall_clearance_mm": 2.0,
            "face_ids": ["F1"],
            "location": [5.0, 5.0, 5.0],
            "origin": "upstream_feature",
        }
        base.update(record)
        return make_model(meta={"bosses": [base]})

    def test_reports_thin_boss_wall(self):
        self.assertEqual(len(run(BossDesignChecker(), self._model(wall_thickness_mm=0.5))), 1)

    def test_wall_boundary_is_accepted(self):
        self.assertEqual(run(BossDesignChecker(), self._model(wall_thickness_mm=0.8)), [])

    def test_reports_insufficient_side_clearance(self):
        self.assertEqual(len(run(BossDesignChecker(), self._model(side_wall_clearance_mm=0.5))), 1)


class TestDfm16Fillet(unittest.TestCase):
    def _model(self, kind, radius):
        return make_model(
            meta={
                "corners": [
                    {
                        "part_id": "P01",
                        "kind": kind,
                        "radius_mm": radius,
                        "nominal_wall_mm": 2.0,
                        "face_ids": ["F1"],
                        "location": [5.0, 5.0, 5.0],
                        "origin": "upstream_feature",
                    }
                ]
            }
        )

    def test_reports_small_inner_fillet(self):
        self.assertEqual(len(run(FilletRadiusChecker(), self._model("inner", 0.4))), 1)

    def test_inner_boundary_is_accepted(self):
        self.assertEqual(run(FilletRadiusChecker(), self._model("inner", 0.5)), [])

    def test_reports_small_outer_fillet(self):
        self.assertEqual(len(run(FilletRadiusChecker(), self._model("outer", 0.8))), 1)


class TestDfm17MultiPull(unittest.TestCase):
    def _model(self, directions):
        return make_model(
            meta={
                "undercuts": [
                    {
                        "part_id": "P01",
                        "direction": direction,
                        "face_ids": ["F1"],
                        "location": [float(i), 5.0, 5.0],
                    }
                    for i, direction in enumerate(directions)
                ]
            }
        )

    def test_reports_multiple_direction_clusters(self):
        found = run(MultiPullDirectionChecker(), self._model([[1, 0, 0], [0, 1, 0]]))
        self.assertEqual(len(found), 1)

    def test_same_direction_is_accepted(self):
        found = run(MultiPullDirectionChecker(), self._model([[1, 0, 0], [1, 0, 0]]))
        self.assertEqual(found, [])

    def test_nearby_directions_share_cluster(self):
        angle = math.radians(10.0)
        found = run(
            MultiPullDirectionChecker(),
            self._model([[1, 0, 0], [math.cos(angle), math.sin(angle), 0]]),
        )
        self.assertEqual(found, [])


class TestDfm18SharpCorner(unittest.TestCase):
    def _model(self, dihedral):
        normal_angle = math.radians(180.0 - dihedral)
        a = make_face("F1", normal=(0.0, 0.0, 1.0), cog=(5.0, 5.0, 5.0))
        b = make_face(
            "F2",
            normal=(math.sin(normal_angle), 0.0, math.cos(normal_angle)),
            cog=(10.0, 5.0, 5.0),
        )
        edge = Edge(edge_id="E1", part_id="P01", face_ids=["F1", "F2"], curve_type="line", length=5.0)
        return make_model([a, b], [edge], [["F1", "F2"]])

    def test_reports_sharp_dihedral(self):
        self.assertEqual(len(run(SharpCornerChecker(), self._model(30.0))), 1)

    def test_boundary_dihedral_is_accepted(self):
        self.assertEqual(run(SharpCornerChecker(), self._model(60.0)), [])

    def test_right_angle_is_accepted(self):
        self.assertEqual(run(SharpCornerChecker(), self._model(90.0)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
