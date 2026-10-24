# -*- coding: utf-8 -*-
"""给一组工况，打印稳态温升。温升没超限时检查项不会出 Finding，用这条看数。

    python -m nxdrp.checkers.m5_performance.predict --area-mm2 15.2 --length-mm 10 --material Cu
"""

from __future__ import annotations

import argparse
import json

from .perf01_current_temp import predict_working_condition


def main() -> None:
    parser = argparse.ArgumentParser(description="按截面积、长度和材料预测稳态温升")
    parser.add_argument("--area-mm2", type=float, required=True)
    parser.add_argument("--length-mm", type=float, required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--current-a", type=float)
    args = parser.parse_args()
    params = {}
    if args.current_a is not None:
        params["current_a"] = args.current_a
    result = predict_working_condition(args.area_mm2, args.length_mm, args.material, params or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
