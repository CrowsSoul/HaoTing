# -*- coding: utf-8 -*-
"""写出模拟 NX 的圆柱端子模型，给 PERF-01 检查用。

    python -m nxdrp.checkers.m5_performance.make_terminal
    python -m nxdrp check nxdrp/checkers/m5_performance/data/simulated_nx_terminal.model.json --only PERF-01
"""

from __future__ import annotations

import argparse

from .simulated_nx_model import MODEL_PATH, save_simulated_nx_terminal


def main() -> None:
    parser = argparse.ArgumentParser(description="写一份模拟 NX 圆柱端子模型")
    parser.add_argument("--out", default=MODEL_PATH)
    parser.add_argument("--diameter-mm", type=float, default=2.0)
    parser.add_argument("--length-mm", type=float, default=8.0)
    parser.add_argument("--material", default="CuSn6")
    args = parser.parse_args()
    path = save_simulated_nx_terminal(
        args.out,
        diameter_mm=args.diameter_mm,
        length_mm=args.length_mm,
        material=args.material,
    )
    print(path)
    print("下一步：")
    print(f"  python -m nxdrp check {path} --only PERF-01")


if __name__ == "__main__":
    main()
