# -*- coding: utf-8 -*-
"""给一组簧片尺寸，打印插入力、拔出力及其区间。

    python -m nxdrp.checkers.m5_performance.predict_insertion --length-mm 10 --width-mm 2 --thickness-mm 0.4 --material CuSn6
"""

from __future__ import annotations

import argparse
import json

from .perf02_insertion_force import predict_insertion


def main() -> None:
    parser = argparse.ArgumentParser(description="按簧片尺寸和材料预测插入力、拔出力")
    parser.add_argument("--length-mm", type=float, required=True)
    parser.add_argument("--width-mm", type=float, required=True)
    parser.add_argument("--thickness-mm", type=float, required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--overlap-mm", type=float)
    parser.add_argument("--contacts", type=float)
    args = parser.parse_args()
    params = {}
    if args.overlap_mm is not None:
        params["overlap_mm"] = args.overlap_mm
    if args.contacts is not None:
        params["contacts"] = args.contacts
    result = predict_insertion(
        args.length_mm, args.width_mm, args.thickness_mm, args.material, params or None
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
