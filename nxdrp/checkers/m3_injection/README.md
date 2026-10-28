# M3 注塑 / 铸造类 DFM

**负责人**：代世航　　**目录**：`nxdrp/checkers/m3_injection/`

## 这个模块在解决什么

塑料件设计出来，模具不一定做得出来：壁太薄注不满、壁厚不均会缩水、拔模角不够会拉伤、有倒扣模具拔不出来。开一次模几十万，改设计不要钱——这 11 项检查就是在开模之前把这些坑找出来。

## 当前实现状态

DFM-08～DFM-18 均已注册并接入管线，包含正例、负例和阈值边界测试。

| 检查项 | 当前数据来源 | 说明 |
|---|---|---|
| DFM-08 / 09 / 10 | 上游 `wall_samples`，否则平行面几何推断 | DFM-09 至少 3 个样本才统计面积占比，避免退化成单值判断 |
| DFM-11 / 12 | 上游 `ribs`，DFM-12 也可用几何推断的 `bosses` | 模具钢净厚按开模方向的垂直投影计算 |
| DFM-13 | 平面法向 + `pull_direction` | 统一开模方向，结果为候选缺陷，分型方向须工艺确认 |
| DFM-14 / 17 | 上游 `undercuts` | 仅凭面法向无法可靠区分倒扣与普通侧壁，缺记录时明确 `skipped` |
| DFM-15 | 上游 `bosses`，否则圆柱面 + 圆形端盖推断 | 可检查凸台壁厚、顶厚、根部 R/壁厚、侧壁净距 |
| DFM-16 | 上游 `corners`，否则环面半径粗筛 | 没有圆角语义时只按内圆角阈值提示，不宣称内外角归属 |
| DFM-18 | 相邻平面的实体二面角 | 可用 `exempt_edge_ids` 配置设计意图边 |

阈值及来源统一维护在公共 `rules/dfm_default.json` 的
`R-DFM-08`～`R-DFM-18`。checker 代码不保存业务阈值副本。

## 可选上游特征记录

平台契约不允许为 checker 私加字段，因此精确特征放在 `ModelBundle.meta`
已有的扩展口子中。没有记录时，能几何推断的项会推断并降低置信度；不能可靠推断的项会跳过。

```jsonc
{
  "meta": {
    "m3_features": {
      "wall_samples": [
        {"part_id": "P01", "thickness_mm": 1.2, "area_mm2": 80.0,
         "face_ids": ["F1", "F2"], "location": [10, 5, 2]}
      ],
      "ribs": [
        {"part_id": "P01", "root_thickness_mm": 0.8, "height_mm": 3.0,
         "face_ids": ["F10"], "location": [10, 5, 3],
         "origin": "upstream_feature"}
      ],
      "bosses": [
        {"part_id": "P01", "outer_radius_mm": 3.0, "wall_thickness_mm": 1.0,
         "top_thickness_mm": 0.8, "root_fillet_radius_mm": 0.4,
         "side_wall_clearance_mm": 2.0, "face_ids": ["F20"],
         "location": [10, 10, 5], "origin": "upstream_feature"}
      ],
      "undercuts": [
        {"part_id": "P01", "direction": [1, 0, 0], "depth_mm": 1.2,
         "face_ids": ["F30"], "location": [10, 5, 2]}
      ],
      "corners": [
        {"part_id": "P01", "kind": "inner", "radius_mm": 0.4,
         "nominal_wall_mm": 2.0, "face_ids": ["F40"],
         "location": [10, 5, 2], "origin": "upstream_feature"}
      ]
    }
  }
}
```

几何推断属于粗筛，Finding 中会写明方法和 `needs_precise_check`。上游特征记录可使用更高置信度。

## 验证命令

```powershell
python -m nxdrp checkers
python -m unittest discover -s nxdrp/checkers/m3_injection/tests -v
python -m unittest discover -s tests
python -m nxdrp check mockdata/models/pressure_port.model.json -r rules/dfm_default.json --only DFM-13
```

## 你负责的检查项

| ID | 名称 | 难度 | 期次 | 判定要点 |
|---|---|---|---|---|
| `DFM-08` | 最小壁厚 | L2 | 一期 | 壁厚 < 材料最小壁厚（PC 1.5 / PA66 0.8 / PBT 0.8 …） |
| `DFM-09` | 均匀壁厚 | L2 | 一期 | 局部壁厚/名义壁厚超出 [0.8,1.25] 的面积占比 > 阈值 |
| `DFM-10` | 壁厚变化 | L2 | 二期 | 相邻区域壁厚梯度超过允许变化率 |
| `DFM-11` | 加强筋设计 | L2 | 一期 | 筋根厚/名义壁厚 ≤ 0.5~0.6；筋高/根厚 ≤ 3~5 |
| `DFM-12` | 模具壁厚 | L3 | 二期 | 筋与筋、凸台与凸台之间模具钢厚度 ≥ 阈值 |
| `DFM-13` | 拔模角 | L1 | 一期 | 面法向与开模方向夹角 < 最小拔模角（0.5°~1°） |
| `DFM-14` | 倒扣 | L2 | 一期 | 沿开模方向存在遮挡（面在投影方向互相覆盖） |
| `DFM-15` | 凸台设计 | L2 | 一期 | 凸台根部 R/壁厚、顶部厚度、凸台与侧壁距离 |
| `DFM-16` | 圆角半径 | L2 | 一期 | 内角缺 R 或 R<0.25t；外角 R<0.5t |
| `DFM-17` | 多抽芯方向 | L2 | 二期 | 统计倒扣方向聚类，>1 个主方向则判定需多抽芯 |
| `DFM-18` | 尖角 | L1 | 一期 | 相邻面二面角 < 阈值（如 60°）且非设计意图 |

## 从哪开始

先做壁厚三件套（DFM-08 / 09 / 10），这一组是整块的地基。

## 三个命令

```powershell
python -m nxdrp checkers                                   # 确认自己被认出来了
python -m nxdrp check mockdata/models/board_a.model.json -r rules/dfm_default.json --only <你的ID>
python -m unittest discover -s tests
```

## 几个提醒

- 拔模角、倒扣这类要面法向的项，M1 还没交付；先写算法骨架并声明 `requires=("normals",)`，框架会跳过不会算错。
- 「碎面与微小特征黑名单」要和 M4 / M6 共用，统一放 `rules/` 下。

## 交之前自查

- [ ] 在 Mock 模型**和**至少一个真实 NX 模型上都跑出正确结果
- [ ] 每条结果带 `face_ids`，工程师能点回 3D 现场
- [ ] 建议能照着改（给目标尺寸或结构动作），不是「请注意检查」
- [ ] 阈值写在 `rules/` 里，代码里只有默认值
- [ ] 数据不够时跳过并说明缺什么，不产出假结果
- [ ] 正例 / 负例 / 边界三个测试都有

写法细节见 `docs/HOW_TO_ADD_A_CHECKER.md`。
