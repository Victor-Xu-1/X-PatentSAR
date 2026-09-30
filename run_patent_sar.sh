#!/usr/bin/env bash
# X-PatentSAR — standalone launcher
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 INPUT_PDF [OUTPUT_DIR] [PATENT_ID] [RUN_OPTIONS...]"
  echo "  INPUT_PDF  : 专利 PDF 路径"
  echo "  OUTPUT_DIR : 输出目录（可选，默认读运营方配置或 XDG state 目录）"
  echo "  PATENT_ID  : 专利编号（可选，自动从文件名提取）"
  echo "  RUN_OPTIONS: 直接传给 'x-patentsar run'；使用 --help 查看完整列表"
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_PDF="$1"
shift
OUTPUT_DIR=""
PATENT_ID=""
if [[ $# -gt 0 && "$1" != --* ]]; then
  OUTPUT_DIR="$1"
  shift
fi
if [[ $# -gt 0 && "$1" != --* ]]; then
  PATENT_ID="$1"
  shift
fi

if [[ -n "${PATENTSAR_PYTHON:-}" ]]; then
  PYTHON_BIN="$PATENTSAR_PYTHON"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi
if [[ "$PYTHON_BIN" == */* ]]; then
  [[ -x "$PYTHON_BIN" ]] || { echo "Python is not executable: $PYTHON_BIN" >&2; exit 2; }
elif ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python command not found: $PYTHON_BIN" >&2
  exit 2
fi

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================"
echo "  X-PatentSAR"
echo "  PDF:  $INPUT_PDF"
echo "  Config: packaged defaults + PATENTSAR_CONFIG_DIR overlays"
echo "============================================"

PIPELINE_ARGS=(run --pdf "$INPUT_PDF")
[[ -n "$OUTPUT_DIR" ]] && PIPELINE_ARGS+=(--output "$OUTPUT_DIR")
[[ -n "$PATENT_ID" ]] && PIPELINE_ARGS+=(--patent-id "$PATENT_ID")

exec "$PYTHON_BIN" -m patent_sar_extractor "${PIPELINE_ARGS[@]}" "$@"
