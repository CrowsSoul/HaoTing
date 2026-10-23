"""Run from the repository root: python -m nxdrp.checkers.m7_platform_web."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="M7 Web 平台（单服务进程）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=4, help="后台任务线程数；不是 HTTP 服务进程数")
    parser.add_argument("--nx-slots", type=int, default=1)
    parser.add_argument("--capacity", type=int, default=100)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    try:
        import uvicorn
        from .backend._server import create_app
    except ImportError as exc:
        parser.exit(1, f"缺少 Web 依赖：{exc}。请安装 M7 requirements.txt。\n")
    app = create_app(args.data_dir, args.workers, args.nx_slots, args.capacity)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
