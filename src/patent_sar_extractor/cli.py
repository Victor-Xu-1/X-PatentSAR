"""Command-line presentation layer for PatentSAR Extractor."""

from __future__ import annotations

import argparse
import logging

from patent_sar_extractor.application.commands import (
    cmd_activity,
    cmd_check_envs,
    cmd_classify,
    cmd_excerpt,
    cmd_health,
    cmd_qa,
    cmd_run,
    cmd_score,
    cmd_smiles,
    cmd_validate,
)
from patent_sar_extractor.contracts import PRODUCT_NAME, __version__
from patent_sar_extractor.core.runtime_env import default_worker_count


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _job_hours(value: str) -> float:
    try:
        hours = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "job lifetime must be a number of hours"
        ) from error
    if not 0.1 <= hours <= 24:
        raise argparse.ArgumentTypeError(
            "job lifetime must be between 0.1 and 24 hours"
        )
    return hours


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"{PRODUCT_NAME} — activity-led patent extraction"
    )
    parser.add_argument(
        "--version", action="version", version=f"{PRODUCT_NAME} v{__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    command = sub.add_parser(
        "run",
        help="正式主链: classify→activity→locate→structures→bind→smiles→final→qa",
    )
    command.add_argument("--pdf", required=True)
    command.add_argument("--output", default="")
    command.add_argument("--patent-id", default="")
    command.add_argument("--force", action="store_true")
    command.add_argument("--reuse-ocr-cache", default="", help="复用经原文 SHA 和观察契约校验的 OCR 缓存；派生结果仍重新计算")
    command.add_argument("--include-intermediates", action="store_true")
    command.add_argument(
        "--skip-advisory-qa",
        action="store_true",
        help="明确关闭可选模型复核，即使已配置模型凭据",
    )
    command.add_argument(
        "--locate-workers", type=int, default=default_worker_count(None, ceiling=4)
    )
    command.add_argument(
        "--bind-workers", type=int, default=default_worker_count(None, ceiling=4)
    )
    command.add_argument("--smiles-workers", type=int, default=1)
    command.add_argument("--gpu-mode", choices=["auto", "force", "off"], default="auto")
    gate_mode = command.add_mutually_exclusive_group()
    gate_mode.add_argument(
        "--strict-gates",
        dest="strict_gates",
        action="store_true",
        default=True,
        help="Fail closed on acceptance errors (standalone default).",
    )
    gate_mode.add_argument(
        "--allow-partial",
        dest="strict_gates",
        action="store_false",
        help="Write review-only partial outputs when strict acceptance fails.",
    )

    command = sub.add_parser("classify", help="阶段工具：确定性页面分类")
    command.add_argument("--pdf", required=True)
    command.add_argument("--output", default="")
    command.add_argument("--force", action="store_true")

    command = sub.add_parser(
        "excerpt", help="诊断工具：生成仅供人工复核的 PDF 摘录（非正式主链）"
    )
    command.add_argument("--pdf", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--metadata", default="")
    command.add_argument("--dpi", type=int, default=150)

    command = sub.add_parser("activity", help="阶段工具：分类后提取活性数据")
    command.add_argument("--pdf", required=True)
    command.add_argument("--output", default="")
    command.add_argument("--cpd-prefix", default="")
    command.add_argument("--include-intermediates", action="store_true")
    command.add_argument("--use-vlm", action="store_true")
    command.add_argument("--force", action="store_true")

    command = sub.add_parser("smiles", help="阶段工具：对已确认绑定运行 DECIMER OCSR")
    command.add_argument("--bindings", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--timeout", type=int, default=60)
    command.add_argument("--limit", type=int, default=0)
    command.add_argument("--include-intermediates", action="store_true")

    command = sub.add_parser("validate", help="诊断工具：校验 Cpd 序列")
    command.add_argument("--known", required=True)
    command.add_argument("--ocr-rows", required=True)
    command.add_argument("--prefix", default="Cpd-")
    command.add_argument("--output", default="")

    command = sub.add_parser("score", help="诊断工具：评分 SMILES 置信度")
    command.add_argument("--smiles-json", required=True)
    command.add_argument("--output", default="")

    command = sub.add_parser("health", help="检查运行环境")
    command.add_argument("--output", default="")
    command.add_argument("--no-gpu", action="store_true")

    sub.add_parser("check-envs", help="检查隔离 Python 环境")

    command = sub.add_parser("qa", help="重新运行确定性正式 QA")
    command.add_argument("--output", required=True)
    command.add_argument("--patent-id", default="")
    command.add_argument("--allow-failed", action="store_true")

    command = sub.add_parser("serve", help="启动本机结构—活性 Web 工作台")
    command.add_argument(
        "--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1"
    )
    command.add_argument("--port", type=_port, default=8765)
    command.add_argument("--state-dir", default="")
    command.add_argument("--frontend-dir", default="")
    command.add_argument("--job-timeout-hours", type=_job_hours, default=24.0)
    command.add_argument(
        "--api-only", action="store_true", help="仅用于前端开发的独立 API 服务"
    )

    command = sub.add_parser("import-run", help="只读导入本机历史结果供 Web 查看与复核")
    command.add_argument("--run-dir", required=True)
    command.add_argument("--pdf", default="")
    command.add_argument("--title", default="")
    command.add_argument("--state-dir", default="")
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    if args.command in {"serve", "import-run"}:
        from patent_sar_extractor.application.web_commands import (
            cmd_import_run,
            cmd_serve,
        )

        {"serve": cmd_serve, "import-run": cmd_import_run}[args.command](args)
        return
    commands = {
        "run": cmd_run,
        "classify": cmd_classify,
        "excerpt": cmd_excerpt,
        "activity": cmd_activity,
        "smiles": cmd_smiles,
        "validate": cmd_validate,
        "score": cmd_score,
        "health": cmd_health,
        "check-envs": cmd_check_envs,
        "qa": cmd_qa,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
