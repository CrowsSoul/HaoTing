"""独立命令入口，无需改平台 cli.py。"""
import argparse
import json
from pathlib import Path
from .core import load_json
from .service import generate_report, list_archives, verify_archive

def demo(output_root, formats=("html", "pdf", "docx"), scene="board_a"):
    from ...contracts import ModelBundle, RuleBook
    from ...pipeline import run
    from ...registry import discover
    root = Path(__file__).resolve().parents[3]
    if scene not in {"board_a", "plate_holes"}:
        raise ValueError("未知示例场景")
    model = ModelBundle.from_dict(load_json(root/f"mockdata/models/{scene}.model.json"))
    rules = RuleBook.from_dict(load_json(root/"rules/dfm_default.json"))
    model.validate()
    result = run(model, rules, discover())
    return generate_report(result, output_root, model=model, rules=rules, formats=formats,
                           mesh=root/"mockdata/_shots/plate_holes.stl" if scene == "plate_holes" else None,
                           title="离线 NX 几何样例检查报告" if scene == "plate_holes" else "连接器设计检查报告")

def main():
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="M8 报告与知识库插件")
    sub = p.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动本地操作界面")
    serve.add_argument("--port", type=int, default=8768)
    serve.add_argument("--archive", default="m8_archives")
    serve.add_argument("--no-browser", action="store_true")
    for cmd in ("generate", "demo"):
        sp = sub.add_parser(cmd)
        sp.add_argument("--out", default="m8_archives")
        sp.add_argument("--formats", default="html,pdf,docx")
        if cmd == "demo":
            sp.add_argument("--scene", choices=("board_a", "plate_holes"), default="board_a")
        if cmd == "generate":
            sp.add_argument("findings")
            sp.add_argument("--model")
            sp.add_argument("--rules")
            sp.add_argument("--screenshots", help="JSON 对象，问题编号映射到 PNG/JPG 路径，路径相对该映射文件")
            sp.add_argument("--mesh", help="与所附模型同坐标系的 STL")
            sp.add_argument("--require-complete", action="store_true", help="数据完整性检查通过才允许生成正式版")
    ls = sub.add_parser("list")
    ls.add_argument("--archive", default="m8_archives")
    ls.add_argument("--query", default="")
    verify = sub.add_parser("verify")
    verify.add_argument("directory")
    audit = sub.add_parser('audit', help='查看报告验收清单；不完整时退出码为 1')
    audit.add_argument('directory')
    args = p.parse_args()
    try:
        if args.command == "serve":
            from .server import serve
            serve(args.archive, args.port, not args.no_browser)
            return 0
        if args.command == "demo":
            result = demo(args.out, tuple(args.formats.split(",")), args.scene)
        elif args.command == "generate":
            shots = None
            if args.screenshots:
                shot_file = Path(args.screenshots).resolve()
                shots = {k: str(shot_file.parent/v) for k,v in load_json(shot_file).items()}
            result = generate_report(load_json(args.findings), args.out,
                                     model=load_json(args.model) if args.model else None,
                                     rules=load_json(args.rules) if args.rules else None,
                                     screenshots=shots, mesh=args.mesh, formats=tuple(args.formats.split(",")), require_complete=args.require_complete)
        elif args.command == "list":
            result = list_archives(args.archive, args.query)
        elif args.command == 'audit':
            directory = Path(args.directory)
            result = load_json(directory/'acceptance.json')
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['data_complete'] else 1
        else:
            result = verify_archive(args.directory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0
    except (ValueError, OSError, RuntimeError, ImportError) as e:
        print("M8："+str(e), file=sys.stderr)
        return 2
