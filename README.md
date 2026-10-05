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

工作台默认只有一件事：上传 PDF，得到结构—活性表，并可在线修正。
界面采用简洁的生物医药工作台视觉：白色内容、冷浅灰背景、近黑操作与系统无衬线字体，
薄荷绿仅用于少量图标、导航和真实状态；次要操作按需展开。保留独立橙色标志，
不复制第三方字体或商标。原文与表格仍是主工作区；修正窗口在宽屏并列展示本地绘图
与编号/列数值，窄屏顺序排列，不增加说明模块或改变提取、保存与验收规则。
`#/new-task` 是默认入口：选择原始 PDF 后点击“开始提取”，软件通过同一个
持久任务先完成严格八阶段提取，释放识别模型后自动计算六项指标。任务名称从
文件名推断；上传页只保留 PDF 和开始提取，不再提供高级选项或隐藏的元数据输入。
新上传沿用安全默认参数：不强制重算、不包含中间体、任务说明为空；完整 ADMET 链路不变。

主工作台左侧为原文，右侧为表格；没有固定导航侧栏、用户头像或多段说明。
未指定页码时默认打开提取结果中最早的结构来源页，不打开封面或活性表第一页。
结构尚未定位时显示等待状态；“浏览原文”可明确打开第一页。手动页码、来源
跳转和 URL 深链接优先，刷新保留这些明确定位。分栏和列宽可拖动/键盘调整，
可收起原文、全屏。任务进度占用一条短栏，真实阶段与资源观测按需展开。

表格最左侧数据列为 Compound 编号，结构裁图单独放在相邻列，不显示 `#` 序号。
批量选择勾选框保留。后续展示专利实测活性、MW、LogP、TPSA、HBD、HBA、LogS 和修正入口。
每种活性独立成列；同名指标的单位、靶点或实验不同时分列，不能混在一个单元格。
列目录来自完整项目的有效观察，搜索和翻页不改变列的身份或顺序；同一实验的
多次观察保留各自的值和来源，不平均、不补值。长表在内部横向滚动，表头、
Compound 编号、结构和行末修正入口固定；编号与结构各自可调整宽度。
每列边界可鼠标拖动或键盘调整宽度。
每个表头的列菜单直接显示 Excel 式搜索、取值勾选、全选及“空白”，按“确定”
才应用，“取消”/Esc/点击外部不改变表格。搜索只查找菜单取值，不自动改动勾选。
多页取值保留选择；全选可用“全部减去未选值”，不把整个大项目塞入 URL。
同列还可按需展开文本/数字条件，或按活性绿色、浅绿色、无色筛选/排序。
支持升/降序、包含/不包含、等于/不等于、开头/结尾、数值范围及空/非空。
多列条件同时生效。排序和筛选作用于完整项目，再分页；刷新与导出保留同一查询。
取值按需加载，遵从其他列和全局搜索、忽略本列已应用条件，便于重新展开选择。
结构图片列只按有无结构筛选，不列出内部图片地址；计算指标不会触发模型。
每列都可隐藏，从工具栏“列”菜单重新展开或恢复全部；冻结列按当前可见列计算位置。
“复制”输出当前页或当前页选中行的可见列 TSV，可粘贴到 Excel；不会复制隐藏字段，
公式前缀经过转义，原值不变。CSV/JSON 导出使用同一完整项目筛选与排序。
活性列自动按同一专利、同一精确实验上下文的全部有效观察相对排名：强档绿色、
中档浅绿色、其余无色。按累计观察数接近三等分选择边界，但相同取值不拆档，
有足够不同取值时保留三档；仅一个取值时全部并列第一，两个取值不虚构中档。
IC/EC/DC/GI50、Ki/Kd 等浓度越小优先，pIC50 等对数指标越大优先；已支持的
竞争型 HTRF ratio 越小优先，加号数量越多优先，Western blot 降解等级 A 优先。
这些是指标约定，不是任意未知实验的方向证明，需对照原文图例。方向不明、
混合值类型、缺失、区间/删失值不猜测排名；超过共享有界统计限额只停止着色，保留数据。
同格多次观察逐值着色，不取平均或最好值。搜索、筛选、翻页、隐藏指标不重新分档；
有效在线活性修订会更新全项目边界，原值和审计不变。颜色仅用于本列比较，
不跨实验/单位比较，不表示绝对药效、有效分子或 QA 通过；六项计算指标不着色。
图例在“列表选项 → 显示选项”，方向、范围与未分档原因在值/表头提示中。
表格不重复显示 `p.xxx` 页码标签：直接点击活性数值定位原文，并圈出该值的
真实来源单元格。结构来源保留图标入口。圈选随原页尺寸和缩放对齐，刷新保留
定位；手动翻页、切换文档视图或选择结构来源会清除旧活性圈选。旧证据只有
页码、缺少单元格/编号证明或坐标方向不明时只翻页并提示，不能猜测位置。
结构页定位和分割不再以活性集合为筛选条件：有结构但未关联活性的原图也保留，
有活性但缺结构的记录也保留。表格是两类原始观察的完整视图，不等于去重后的
化合物清单。绑定阶段先建立原文编号目录，再按编号关联活性，不把活性集合当作编号全集。
已证实编号的无活性结构使用真实 Compound 编号；选定子表中经过编号与空间证据确认的
重复结构，归到同一编号的其他出处，不追加成匿名行。未经证实或存在冲突的编号仍
显示“编号待确认”，不根据结构相似或顺序猜测编号。
“未关联活性”不表示阴性或没有活性。正式绑定、OCSR 和严格 QA 仍以活性集合
为正式关联验收范围；同一个 OCSR 批次同时识别编号已确认的无活性结构，使用
完全相同的原图、DECIMER、RDKit 和手性风险校验。合格结构都进入同一六指标
计算入口，不检查是否有活性数据；编号、原图、SMILES、重绘、来源及修正能力
采用相同标准。未确认编号、缺图或识别失败仍保留原图/定位和明确状态，不能
猜测归属或计算值。SMILES v2 的 `records` 保留正式关联顺序，`source_records`
保留其他已证明编号的观察；旧产物不改写。已有项目用“补齐结构与指标”，由软件
先识别尚未合格识别的已证实编号结构，再计算六项指标；无需重新提取整份 PDF。
新增观察独立持久保存，表格、结构详情、修正和导出共用同一读数路径。
同一原文的后续补齐任务复用原始识别缓存，按精确图像和模型指纹匹配后重新校验；
不重复加载已覆盖的模型，也不复制旧 QA、人工修正或预测表。
前五项来自结构描述符计算，LogS 为 ADMET-AI 2.0.1 的模型预测；
这些值不是专利实测，也不证明分子有效、安全或适合临床。每条活性保留自己的
单位、靶点、实验与原文页，等级和删失值不被强制变成数值。缺失、失败、等待或
过期预测显示明确状态，不能填入替代值。模型适用域和原图—SMILES 精确一致性
仍需独立验证，尤其是大分子 / PROTAC。

点击行末修正，直接用本地 Ketcher 画结构、修改编号、各列活性和六项指标，再保存。
窗口仅保留这些输入与保存/取消；结构缩略图放大且无外框。Ketcher 按需加载，
浏览器内完成绘图和格式转换，不另建后端服务、不上传分子到第三方。
修订有独立审计与并发版本检查；Molfile 与 SMILES 的分子图、手性、同位素、盐和电荷
必须一致。原 PDF、原始裁图、正式流水线产物和原始 QA 不被覆盖；改变分子图后只自动重算
该化合物，不重跑整份 PDF；仅改坐标、编号或数值不触发模型。旧预测按来源 / 分子图指纹失效。
手工指标独立保存，筛选、复制和导出使用相同有效值；手工留空不借用模型数值。原始裁图与当前
SMILES 的 RDKit 重绘可并排对照；重绘和 token 概率都不证明识别正确。
含人工修正、计算指标或未关联观察的导出明确为复核 / 研究材料，原始正式 QA
只覆盖其原有的活性关联范围，不把额外结构冒充为已验收的化合物。
搜索、分页、CSV/JSON 导出保留；筛选、统计、验收详情与历史项目的“补齐结构与指标”
在列表选项中。上传 PDF、最近文件、环境管理和任务记录直接平铺在顶栏，版本同栏显示；
项目工作台还直接显示返回结果表格和证据摘要入口。窄屏按需换行，按钮文字不隐藏。

软件沿用一个 CLI 提取权威与一个 ADMET 推理服务，不增加第二套识别引擎、
第三方云预测或付费建议模型。正式八阶段 QA 仍 fail closed；研究指标是否完成
与原始 QA 分开记录。状态、模型、缓存、测试证据都留在外部 E 盘目录。

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

### 环境管理

顶栏直接显示的 **环境管理**（`#/settings`）以完整环境状态和**一键部署全部环境**为主入口。
软件安装并启动后，一次确认即可建立一个完整后台任务，自动处理安装工具、基础 PDF/OCR/RDKit、
DECIMER 运行环境与模型、ADMET CPU 环境与模型。用户不需要逐项安装或手工拼装路径。
后端先真实检查已有组件，合格的直接复用，缺失或不兼容的安装到新私有前缀；六项全部通过
后才统一发布配置。已有文件不覆盖，检测超时/资源不足不会被误判为需要重装。
已全部就绪时不重复部署，主入口提供完整复检。默认页面只保留总体状态、部署和运行中进度/取消；
版本、路径、位置修改和组件检查在独立的环境详情入口中。日志、操作历史及内部编号不进入日常
操作界面，仍在后台持久保留供运营排查。目录直接显示配置路径是否存在；路径存在不代表检查通过。已验证组件显示
“已安装 · 已验证”，已有但未验证/检测过期的路径显示待检测/待复检，不重复提示安装。
目标版本与实测版本分开，过期版本/检查只显示在同一路径的历史记录中；改了路径不借用
旧环境的结果。每项组件保留自己的检测时间，检测少数组件不会刷新其他组件的时间。
完整复检会真正检查解释器、锁定的包版本、PDF/OCR/RDKit
及 CPU 模型加载，不会触发下载。安装前会展示完整依赖、版本及许可证；确认后
在后台安装，主页面仅显示进度并支持取消，刷新页面不会丢失任务。

“一键”指一个完整计划和一个持久操作，不是取消下载/许可证确认，也不是自动配置 WSL、GPU、
系统软件或付费服务。主程序的 Linux/WSL2 x86_64、Python 3.12 与 Web 启动环境须先就绪；
运行中的科学依赖和权重随后由软件自行配置。Ketcher 已随 wheel 打包，不再额外部署服务。

组件只有受管 uv、基础 PDF/RapidOCR/RDKit 环境、DECIMER 环境及权重、
ADMET CPU 环境及权重。主应用和科学环境隔离；不安装系统级包、不要求管理员，
不隐式安装 CUDA、其他平台或付费模型。已有环境先验证后复用；新环境使用
独立前缀，全部验证通过才写入外部 `env_paths.local.yaml` 并供新任务使用。
失败、取消、重启中断或配置冲突均不会启用半成品，不改变既有专利结果。检测期间
配置或配方变化时保留操作记录，但不把旧快照的结果发布为新环境已验证。

本机 E 盘部署将以下配置放在仓库外的启动入口。Linux 路径实际位于 E 盘 WSL
虚拟磁盘内；浏览器不接受 C 盘、UNC、Windows 挂载目录或任意软件安装命令。

```bash
export PATENTSAR_ENVIRONMENT_ALLOWED_ROOT=/srv/wsl/envs
export PATENTSAR_ENVIRONMENT_ROOT=/srv/wsl/envs/x-patentsar-managed
x-patentsar serve --port 18765
```

其他部署可选择自己的外部 Linux 存储根目录。所选安装目录应为不存在的新目录，
或已经由本软件管理、权限为 0700 的私有目录；未知旧内容一律保留并拒绝覆盖。
显式环境变量优先于保存配置，所以运营入口不应再对模型路径设置固定的隐式
覆盖。位置调整仅影响后续新安装，不自动迁走、删除或重建已有环境。详细恢复、
许可证和手动安装边界见 `docs/OPERATIONS.md` 与 `NOTICE`。

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

不安装外部模型环境仍可读取已有 PDF、提取结果、修正、导出和证据摘要；
完整 Web 任务要求 ADMET 环境就绪。缺失预测环境会明确阻塞或失败，不生成替代值。模型输出不是实验结果，适用域未经过本项目
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
- 准确性规则集：`patentsar.accuracy-first` `2.0.4`；产品仍为 `v0.1.0`。
- 产物/缓存 Schema 各自独立递增：页面分类、绑定与 SMILES 为 `2`，正式 QA 为 `3`；其余当前产物与缓存为 `1`。

唯一权威来源是 `src/patent_sar_extractor/contracts.py`。所有可复用缓存和正式 JSON 产物均使用 `schema`、`product`、`pipeline_contract`、`ruleset` 身份信封；旧插件缓存不会被当前版本误复用。

活性表和普通编号结构表共用原页网格、单元格读取及一个受限线程的 OCR 引擎。
已识别页面有唯一解析归属，不再进入竞争的通用 OCR/顺序推算分支。结构绑定
必须证明打印编号、相邻结构单元格和唯一完整 DECIMER 裁图的对应关系；缺图、
跨格、重复编号或字母后缀不明确时严格失败。每项活性保留各自页码、表格及
单元格观察证据，前端不会把多个实验统一标到合并行的第一页。

完整结构目录与明示的“选定化合物”重复子表分别归属；只有编号集合证明为
完整目录子集且对应格内结构证明成立时，才作为同一编号的其他原文出处保留，
真正的重复/冲突继续失败。编号目录的独立 schema 为 `patentsar.compound-catalog` v1，
嵌入同一个绑定产物；绑定实现指纹为 5，产品仍是 v0.1.0。表外结构须有
完整的原文图下注释与唯一空间归属，`8A` 等后缀不会退化成父编号。
全部活性化合物已有确定的原文空间证据时，软件跳过通用多轮补漏，而不是
重复裁图 OCR。运行中已完成的检查点会展示为候选结果，正式通过仍以最终 QA
为准；切换到新运行会自动清除上一轮的界面结果。

正式 OCSR 只保存和校验 DECIMER 的原始字符串，不再猜测元素字母、修环编号、
删原子/片段、补同位素或根据编号翻转手性。非干净预测可对同一截图做一次
有记录的图像标准化重试；仍不合格则保留原始候选并严格停止，不能修改字符串
凑出可导出的分子。模型原始观察使用独立缓存版本，旧自动修补缓存不会被提升
为新版正式结果。

所有新任务统一执行原图手性风险检查。检测到波浪/未知键图形而模型给出确定
构型时，保留原始候选、标记冲突并阻止正式验收；多中心无法对应时明确待核对，
不删除 `@`、不按编号猜测 R/S，也不把未知构型当作外消旋体。缓存原始观察同样
重走当前校验。检查未发现未知键不等于已验证绝对构型；图像风险观察不替代完整
原子/键对应验证。产品版本不变，规则集独立更新，旧专利结果保留为历史证据。

规则变更后建立新运行记录，旧失败产物保留。Web 新任务自动复用同一私有项目
内、原文 SHA 与观察契约一致的 OCR 原始缓存；活性、定位、绑定及 QA 全部按
当前规则重算。独立 CLI 可显式使用 `run --reuse-ocr-cache /path/to/page_ocr_cache.json`。
该选项不能与 `--force` 合用，也不会复用旧版正式结果。原始观察的兼容范围独立
登记在契约文件中，明确排除缺少一致坐标的旧 `2.0.0` 缓存。

## 测试与打包

按实际修改选择定向回归及直接消费者；下列测试是本次表格/修正模块的示例，
不表示每次固定执行同一批。未经用户明确授权，不运行全局测试。

```bash
uv sync --frozen --extra web
uv run python -m unittest tests.test_structure_corpus tests.test_corpus_predictions -v
cd frontend
npm ci
npm run typecheck
npm run lint
npx vitest run tests/simple-table.test.tsx tests/corrections.test.tsx --maxWorkers=1
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
