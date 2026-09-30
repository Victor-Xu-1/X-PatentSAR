# X-PatentSAR

开源仓库：[Victor-Xu-1/X-PatentSAR](https://github.com/Victor-Xu-1/X-PatentSAR)。
软件与仓库的对外名称统一为 **X-PatentSAR**；Python 发行包与 CLI 使用规范化技术标识
`x-patentsar`。第一方源码采用 Apache-2.0，第三方许可和模型边界见 `NOTICE`。

独立运行的专利化学结构、活性数据与结构—活性关系（SAR）提取软件。当前生产适配器面向 WIPO 专利 PDF，主链为：

```text
classify -> activity -> locate -> structures -> bind -> smiles -> final -> qa
```

软件默认 fail closed：结构绑定、SMILES 或最终 QA 未满足严格规则时，命令以失败状态结束，结果不能作为正式交付。`--allow-partial` 仅保留人工复核材料，不代表验收通过。

## 支持范围

- 运行平台：Linux / WSL2；当前版本在 Ubuntu WSL2 验证。
- 主程序：CPython 3.12。
- OCSR：生产主链仅接受 DECIMER；RDKit 负责 SMILES 校验与标准化。
- LLM/VLM：仅用于可选的活性表复核和建议性 QA；生产页面分类为确定性规则，模型不能改变正式验收。
- 交付物：Excel、SDF、结构裁图、带身份信封的绑定/SMILES JSON、流水线摘要与 `final_qa_report.json`；可选模型建议写入独立的 `llm_qa_report.json`。

独立版不依赖 Synon 后端、插件 manifest 或 `.synon` 目录。

## Web 工作台

工作台使用中文界面，视觉参考 Claude 浅色工作台：米白画布、灰米色侧栏、
深墨控件、陶土色强调与衬线标题。保留独立 X-PatentSAR 品牌，不使用其
专有字体或商标；统一设计变量位于 `frontend/src/styles/tokens.css`。
提供原始 PDF 页图/文本、结构与活性表、来源定位、
筛选分页、人工复核、CSV/JSON 导出及提取任务管理。
`#/new-task` 是完整任务输入页，默认建立项目并启动严格提取；可明确选择仅建项目。
任务备注、包含中间体和强制重算选项会实际保存/执行，备注不是给 LLM 的指令。
结果区默认占分栏宽度 72%，支持拖动/键盘调整、收起原文和全屏，布局随 URL 保留。
它调用下方同一条 CLI
主链；人工批准只记录复核意见，正式验收仍由确定性 QA 决定。历史导入保留
历史身份。本地分子分析接入 DECIMER 裁图识别、RDKit 校验和 ADMET-AI v2 CPU
预测，结果标明研究用途，与专利实测活性和正式 QA 分开。证据摘要是基于真实
记录、单位和删失值的确定性统计，不冒充 LLM 摘要或推测药效。

从源码安装 Web 依赖并构建界面（Node.js 24.21.x）：

```bash
uv sync --frozen --extra web
uv run python tools/build_environment_resources.py --check
cd frontend
npm ci
npm run build
cd ..
uv run python tools/build_frontend.py
uv run python tools/build_frontend.py --check
uv run x-patentsar serve --port 8765
```

打开 `http://127.0.0.1:8765/`。默认只监听本机，首次同源访问建立本机会话，
写入请求必须通过 CSRF 校验。Web 状态默认写入主状态目录的 `web` 子目录，
可使用 `PATENTSAR_WEB_STATE_DIR` 或 `serve --state-dir` 指定独立目录。

本机 E 盘部署使用 `http://127.0.0.1:18765/`，Windows 入口是
`E:\WSL\apps\x-patentsar\X-PatentSAR.cmd`；8765、8766 留给现有应用。
Linux 源码、环境和数据仍位于 E 盘 `E:\WSL\system\ext4.vhdx` 内，
实际路径通过 `E:\WSL\apps\x-patentsar` 入口统一管理。

只读接入已有运行结果（先停止使用同一状态目录的工作台，再导入并重新启动）：

```bash
x-patentsar import-run --run-dir /path/to/existing/run --title "历史专利复核"
```

可加 `--pdf /path/to/original.pdf`；历史产物记录了原文 SHA-256 时必须一致。
没有原文时保留真实裁图和历史 OCR，界面明确显示原文未提供。
单个 Web 提取任务默认最长 24 小时，可用 `serve --job-timeout-hours` 设置
0.1–24 小时范围；超时会明确失败并提供恢复状态，不会自动放宽 QA 门禁。

## 可选本地 ADMET 环境

ADMET-AI 2.0.1 使用 Chemprop/PyTorch，在独立 Linux x86_64 Python 3.12 CPU
环境安装，不混入主程序或 DECIMER/TensorFlow 环境。完整版本和下载哈希位于
`src/patent_sar_extractor/defaults/environments/admet-cpu-requirements.txt`；这是外部模型运行边界，不是主应用
`uv.lock` 的第二套依赖权威。

```bash
if [ ! -e /srv/wsl/envs/x-patentsar-admet ]; then
  uv venv /srv/wsl/envs/x-patentsar-admet --python 3.12
fi
uv pip sync --python /srv/wsl/envs/x-patentsar-admet/bin/python \
  --require-hashes --torch-backend cpu src/patent_sar_extractor/defaults/environments/admet-cpu-requirements.txt
mkdir -p /srv/wsl/cache/patentsar/analysis-wheels
curl --fail --location --connect-timeout 10 --max-time 300 \
  https://files.pythonhosted.org/packages/12/19/5d83e84207636e6dd655b7cefab95c04eb5a48e7eaa1151424370b1a6ff1/admet_ai-2.0.1-py3-none-any.whl \
  --output /srv/wsl/cache/patentsar/analysis-wheels/admet_ai-2.0.1-py3-none-any.whl
uv run python tools/prepare_admet_models.py \
  --wheel /srv/wsl/cache/patentsar/analysis-wheels/admet_ai-2.0.1-py3-none-any.whl \
  --model-dir /srv/wsl/models/patentsar/admet-ai/2.0.1
export PATENTSAR_ADMET_PYTHON=/srv/wsl/envs/x-patentsar-admet/bin/python
export PATENTSAR_ADMET_MODEL_DIR=/srv/wsl/models/patentsar/admet-ai/2.0.1
export PYSTOW_HOME=/srv/wsl/models/patentsar
uv run x-patentsar serve --port 8765
```

运营方可将 `/srv/wsl` 替换为自己的外部存储根目录。若已缓存官方轮子，可在
`uv pip sync` 加 `--find-links /path/to/verified-wheels`；仍必须保留哈希校验。
准备工具验证官方 wheel SHA 与十个模型的内容指纹，不替换未知旧内容，也不
复制或使用 DrugBank 参考分子。分析子进程禁止网络，CPU 单并发、最长 180 秒，
收到取消或服务关闭时只清理已核实的本软件进程。

不安装外部模型环境仍可使用 PDF、提取、复核、导出和证据摘要；分子预测会
明确报告环境缺失，不生成替代值。模型输出不是实验结果，适用域未经过本项目
验证；大分子/PROTAC 尤其不能直接据此宣称有效、安全或具有某种临床性质。

## 安装

```bash
cd /srv/wsl/projects/patent-sar-extractor
python3 -m venv /srv/wsl/envs/patentsar-uv-bootstrap
/srv/wsl/envs/patentsar-uv-bootstrap/bin/python -m pip install uv==0.11.31
/srv/wsl/envs/patentsar-uv-bootstrap/bin/uv sync --frozen
source .venv/bin/activate
```

DECIMER-Segmentation 1.5.0 依赖 TensorFlow 2.12–2.15，不能安装进主程序的 Python 3.12 环境。请使用隔离的 Python 3.10 环境：

```bash
conda create -n patentsar-decimer python=3.10 -y
conda run -n patentsar-decimer python -m pip install \
  DECIMER==2.8.0 DECIMER-Segmentation==1.5.0 tensorflow==2.15.1 numpy==1.26.4
export DECIMER_PYTHON="$(conda run -n patentsar-decimer python -c 'import sys; print(sys.executable)')"
```

上面的环境创建命令要求已安装 Conda。分割需要 `DECIMER-Segmentation`，图片转 SMILES 还需要 `DECIMER`，两者不能混为一个依赖。本轮已验证旧系统恢复出的 Python 3.10.20、DECIMER 2.8.0、Segmentation 1.5.0、TensorFlow 2.15.1、NumPy 1.26.4 组合，以及主程序的全新隔离 wheel 安装；另建全新 DECIMER 环境的冷安装验收尚未执行。

系统层建议安装 Tesseract。若使用 PaddleX HTTP OCR，请设置 `PATENTSAR_PADDLEX_OCR_URL`。DECIMER/TensorFlow 与 CUDA 必须按实际 GPU 驱动验证，不能仅凭包安装成功判断 GPU 可用。

## 配置与运行状态

复制环境变量模板，只在本机填写真实凭据：

```bash
cp .env.example .env
set -a
source .env
set +a
```

配置优先级从高到低为：

1. 环境变量；
2. `$PATENTSAR_CONFIG_DIR/*.local.yaml`；
3. `$PATENTSAR_CONFIG_DIR/*.yaml`；
4. wheel 内的安全默认值。

未设置 `PATENTSAR_CONFIG_DIR` 时，运营方配置目录为 `${XDG_CONFIG_HOME:-~/.config}/patent-sar-extractor`。未显式指定输出且配置中也没有 `output_dir` 时，运行结果写入 `${PATENTSAR_STATE_DIR:-${XDG_STATE_HOME:-~/.local/state}/patent-sar-extractor}/runs/<patent-id>`。

示例覆盖文件位于 `examples/config/`：

```bash
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/patent-sar-extractor"
cp examples/config/llm.local.example.yaml \
  "${XDG_CONFIG_HOME:-$HOME/.config}/patent-sar-extractor/llm.local.yaml"
```

常用变量包括 `LLM_API_KEY`、`LLM_ENDPOINT`、`PATENTSAR_BASE_PYTHON`、`SMILES_ENGINE_PYTHON`、`DECIMER_PYTHON` 和 `PATENTSAR_PADDLEX_OCR_URL`。完整列表见 `.env.example`。未使用的解释器变量保持空值，避免覆盖已经配置好的 `env_paths.local.yaml`。

本机 E 盘部署入口为 `E:\WSL\apps\x-patentsar\X-PatentSAR.cmd`，Linux 运营入口为 `/srv/wsl/envs/patentsar/bin/x-patentsar`。本机配置、状态、模型、缓存分别位于 `/srv/wsl/data/patentsar/config`、`/srv/wsl/data/patentsar/state`、`/srv/wsl/models/patentsar`、`/srv/wsl/cache/patentsar`。DECIMER 恢复环境保留原 Linux 路径以免破坏 Conda 前缀，但其物理存储同样在 E 盘 VHDX 中。入口默认使用 CPU，GPU 未经过兼容性验收不能默认启用。

先检查命令与环境：

```bash
x-patentsar --version
x-patentsar check-envs
x-patentsar health --no-gpu --output /tmp/patentsar-health.json
```

运行完整主链：

```bash
x-patentsar run \
  --pdf /path/to/WO2024037616.pdf \
  --output /srv/patentsar/output/WO2024037616 \
  --patent-id WO2024037616
```

源码检出也提供 Bash 包装器：

```bash
./run_patent_sar.sh /path/to/patent.pdf /path/to/output WO2024037616 --force
```

`run` 是唯一正式交付链路。`classify`、`activity`、`smiles`、`qa` 用于阶段级复跑或检查；`excerpt`、`validate`、`score` 是诊断工具。旧式独立 `profile`/`bind`/`truncate` 命令已移除，避免绕过“活性集合与顺序是唯一权威”的主链约束。`excerpt` 生成的 PDF 摘录仅供人工复核，正式链路始终使用原始 PDF 的页码坐标。

## 版本与数据契约

- 产品版本：`0.1.0`，遵循 Semantic Versioning。
- 流水线契约：`patentsar.activity-led` `2.0.0`。
- 准确性规则集：`patentsar.accuracy-first` `2.0.1`。
- 产物/缓存 Schema 各自独立递增：页面分类、绑定和正式 QA 当前为 `2`；其余当前产物与缓存为 `1`。

唯一权威来源是 `src/patent_sar_extractor/contracts.py`。所有可复用缓存和正式 JSON 产物均使用 `schema`、`product`、`pipeline_contract`、`ruleset` 身份信封；旧插件缓存不会被当前版本误复用。

## 测试与打包

```bash
uv sync --frozen --extra web
uv run python -m compileall -q src tests tools
uv run python -m unittest discover -s tests -v
cd frontend
npm ci
npm run typecheck
npm run lint
npm run test
npm run build
cd ..
uv run python tools/build_frontend.py
uv build --wheel --out-dir dist
```

真实浏览器测试在已启动的本机服务上运行：

```bash
cd frontend
npx playwright install chromium
PATENTSAR_E2E_BASE_URL=http://127.0.0.1:8765 npm run e2e
```

WSL 本机设置 `PLAYWRIGHT_BROWSERS_PATH=/srv/wsl/cache/ms-playwright`，避免把
浏览器下载和测试记录放在 C 盘。安装已构建的独立 wheel 使用
`python -m pip install 'x_patentsar-0.1.0-py3-none-any.whl[web]'`；wheel 含界面，
运行时无需 Node.js。源码构建和测试需要 Node.js。

## 代码结构

- `src/patent_sar_extractor/application/`：主链用例、缓存/验收策略与跨阶段调度。
- `src/patent_sar_extractor/core/`：确定性分类、提取、绑定、DECIMER OCSR 与正式 QA。
- `src/patent_sar_extractor/integrations/`：可选 LLM/VLM 外部服务适配；无正式验收权。
- `src/patent_sar_extractor/workers/`：隔离 Python 环境执行的子进程入口。
- `src/patent_sar_extractor/defaults/`：只读、安全、可移植的打包默认配置。
- `src/patent_sar_extractor/cli.py`：仅负责参数解析和命令分发。
- `src/patent_sar_extractor/web/`：本机 API、持久化、进程生命周期与只读产物适配。
- `frontend/`：React/TypeScript 界面、API 契约检查与交互测试。
- `tools/`：可复现的 Web 构建与打包检查。
- `examples/config/`：运营方覆盖配置模板。

详细说明见 [架构文档](docs/ARCHITECTURE.md) 和 [运维文档](docs/OPERATIONS.md)。

## 数据和安全

- 不要提交专利原文、结构图片、输出 Excel、模型权重、缓存、日志或密钥。
- PDF、LLM 输出、OCR 文本和外部服务响应都按不可信输入处理。
- 每项专利使用独立输出目录，不要让两个进程同时写同一目录。
- 失败时检查 `pipeline_summary.json`、`final_qa_report.json` 和 `STRICT_ACCEPTANCE_FAILED.json`。

## 迁移与回滚

当前独立源码位于 E 盘 WSL 的 `/srv/wsl/projects/patent-sar-extractor`。恢复前的原始源码归档仍在 `E:\WSL\archives\projects`；历史运行数据保留在恢复时的原路径 `/home/victor_1/.local/state/patent-sar-extractor`，新任务使用独立状态目录，不覆盖历史结果。回滚需停止本软件任务并恢复已保留的源码/入口，不必停止 C 盘 Ubuntu；不要把运行产物复制回源码树。

产品名称、Python distribution 和对外命令统一为 X-PatentSAR / `x-patentsar`；版本保持 `v0.1.0`。内部 Python 包 `patent_sar_extractor`、`PATENTSAR_*` 配置和既有数据路径是稳定技术命名，保留以避免破坏历史运行数据与环境前缀。Web 集成和验收进度记录在 `docs/WEB_API.md`，任何历史诊断数据都不能作为当前正式提取已经验收的证明。

许可证：[Apache-2.0](LICENSE)。第一方源码受该许可证约束；专利、用户数据、外部模型和第三方库不因此改许可，见 [NOTICE](NOTICE)。
