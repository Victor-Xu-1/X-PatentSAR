# X-PatentSAR 前端

单一 React / TypeScript 工作台，仅调用控制方维护的 `docs/WEB_API.md` v1 API。
没有生产演示数据、请求失败回退或第二套正式提取引擎。
完整任务输入、结果优先布局、真实原文与分子分析调用同一后端。
ADMET 来自本地模型接口；证据摘要是确定性统计，明确不是 LLM 摘要。
页面产品版本来自 `/api/v1/health`；package 版本是前端交付元数据，不能替代 Python 版本权威。

## 安装与开发

在 E 盘 WSL 工作树的 `frontend` 目录运行，使用 Linux Node 24.21.0，不使用 Windows Node。

```bash
export PATH=/srv/wsl/envs/node-v24.21.0-linux-x64/bin:$PATH
export npm_config_cache=/srv/wsl/cache/npm
export TMPDIR=/srv/wsl/tmp
export PLAYWRIGHT_BROWSERS_PATH=/srv/wsl/cache/ms-playwright
export NODE_OPTIONS=--max-old-space-size=2048
npm ci --ignore-scripts
PATENTSAR_API_PROXY_TARGET=http://127.0.0.1:18765 npm run dev
```

Vite 只监听 `127.0.0.1:5173`。代理默认目标为 `http://127.0.0.1:8765`，可通过
`PATENTSAR_API_PROXY_TARGET` 指向已由运营方启动的服务。本机 8765/8766 已被其他项目占用，
不要在这些端口启动或停止服务。前端不会启动或终止 API。
代理只接受 loopback HTTP origin，开发时将匹配 Vite 自身 origin 的请求 origin 转给目标 API；
生产构建无代理配置或外部 API 地址，全部请求使用同源 `/api/v1`。
不需要前端密钥或 `.env` 文件，不能把秘密放入 `VITE_*` 环境变量。

## 检查与构建

```bash
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
```

输出在忽略的 `frontend/dist`。Vite 自动生成 `THIRD_PARTY_LICENSES.md` 并关闭 source map。
主线程负责把整个 dist 的 HTML、assets 和第三方许可文件打入 wheel 的 `web/static`；
不要单独提交 dist 或在前端修改 Python 包装规则。生产以同源 HTTP 服务打开，不能用 `file://`。
本地构建预览可用 `npm run preview`，但它不代理 API，不能代替集成后的 API 服务。

## 模块边界

- `src/api`：契约类型、运行时数据校验、会话 bootstrap、cookie / CSRF、请求期限和响应大小边界。
- `src/model`：刷新可复现的 hash 路由、来源展示与 PDF 上传校验；`results.ts` 只做指标目录、实验上下文分组与独立状态投影。
- `src/hooks`：中止过期读取、错误可见的加载状态、仅活跃任务轮询、搜索防抖。
- `src/components`：导航、语义化反馈、键盘 tabs、原生 modal dialog、受限同源图片。
- `src/features`：工作区、PDF 视图、真实结果、项目、任务与环境管理。
- `src/features/tasks`：两阶段真实上传/作业创建，未知写入结果不自动重放。
- `src/features/analysis`：批量 SMILES、研究用途识别/预测与证据摘要；不回写正式产物。
- `src/features/environment`：批准的安装位置、服务端组件/推荐组合、确认安装、持久化操作/日志与恢复核对。
- `src/styles`：按布局、PDF、表格、管理页、对话框与视口拆分。
- `tests`：隔离契约输入和行为测试；不会进入生产打包。
- `e2e`：真实服务的 Playwright 验收，没有拦截 API 或 seed 路由。

## 数据与操作边界

页面原图、裁图、文本、标注、统计和任务阶段都来自 API。历史结果保留来源提示，缺失原始
PDF 时不制造页面。活性值原样展示，等级值不会强行改成 IC50。绑定证据缺少数值时显示未知/无数值。
人工复核使用 `expected_revision`，409 后保留草稿，要求显式读取最新版本再保存；永不改变核心 QA。

服务端支持关键词、靶点、置信度、复核状态和分页。现有 API 未提供 metric 查询参数，
“指标列”提供多选与“显示全部指标”，只控制显示，不改变服务端化合物总数、分页、选择或导出。
目录合并服务器 metrics 与当前页实际 Activity 名称，避免遗漏目录未列出的真实指标。
默认紧凑视图，舒适视图展示完整实验描述。相同 target/assay 上下文只显示一次，以实验编号
对应各指标值；每个观察仍保留自己的单位、值、页码与来源按钮，不借用结构页或同实验其他指标页。
同名指标的多个观察不会合并或删除。活性来源跳转打开原文并清除结构标注选择；结构来源仍走原有标注定位。
密度与指标选择是当前结果视图的展示状态，刷新后回到默认紧凑/全部指标，不写个人浏览器存储。
选择跨结果页保留，修改搜索/筛选会清空选择。导出选择明确发送真实 IDs；“全部结果”发送空 IDs，
明确不受当前表格筛选限制。“当前筛选结果”通过既有 export 端点的 q/confidence/review/target
查询参数导出所有匹配页，不发送分页参数，不把当前页当作全部匹配结果。未接受的项目始终提示仅供复核。

绑定证据（confidence）、识别校验（recognition）、人工复核（review）是三种独立状态。
RDKit 的 valid 仅标为“可解析”，不代表识别与原图一致，更不是人工通过。模型 token confidence
保留服务端最小值/均值，并明确“未校准，不是结构正确率”。未提供识别字段时显示“识别状态未知”，
不根据已有 SMILES 或高绑定证据推断识别结论。
顶部 needs_review 明示为“绑定待核验”；manually_reviewed 只计 approved/rejected 的已判定记录，
manual_review_pending 计 review=null 或 needs_review。两个计数直接来自控制方真实 SQL 聚合，
未提供时显示“未知”，不从当前页、活动行数或绑定统计估算。
因此统计条使用“人工待复核”，包括已有注记但仍需复核的化合物；六项统计保持单行紧凑条，
窄屏仅在条内横向滚动，不叠成多排卡片挤占结果表高度。DECIMER 负责识别，RDKit 负责校验与重绘。

点击编号即可打开结构详情，即使原始裁图尚未生成。原始 PDF crop 与规范化 SMILES 的 RDKit
PNG 重绘始终并排，标明原文证据与派生图的区别；无 SMILES、无图、无效 URL、图片加载失败
均有独立状态，不把原图当重绘。redraw_image_url 由服务端提供，只接受同源
`/api/v1/projects/{project_id}/structures/{compound_id}/redraw`，完整保留 content digest 查询参数，
从而随新运行内容更新图片。独立 DECIMER/ADMET 分析不会改写这里的核心 canonical SMILES 或任何产物。

Stage 的 progress 与 reused_checkpoint 仅展示服务端观察：completed/total、缓存命中、失败数、
CPU/GPU、峰值 RSS（MB）及检查点复用；没有进度、设备、RSS 或复用字段时明确未知/未提供。
资源与缓存详情由可键盘打开的阶段控件展示，不估计百分比或 ETA。history_available=false 时
明确旧共享目录无法可靠还原本次历史，不展示该目录的成功阶段、计数或进度；字段缺失同样不推断成功。
继续使用现有 job 读取/轮询链路，未增加进度 poller；仅进度/耗时变化不会重新查询整张结果表。

读取只对网络故障/502/503/504 有一次有界退避重试；写入不自动重试。
不确定写入先刷新检查状态，不应直接再次提交。身份过期可通过重新加载建立会话。
JSON 默认限 8 MiB，导出限 128 MiB；PDF 前端限制 128 MiB，服务端仍须真实解析、SHA 验证和鉴权。

## 验证范围与真实浏览器

本包回归覆盖会话/CSRF、原始 PDF 上传、路由刷新、响应和几何校验、取消过期请求、来源定位、
真实值展示、分页/选择、复核冲突、导出、任务运行取消恢复、错误/空/禁用状态与基础键盘焦点。
隔离测试只能证明前端契约与交互，不能证明后端、数据库、提取模型或真实 PDF 流水线可用。
Python 全套门禁、wheel 安装、API 安全与真实提取由主线程完成，不在本前端分支修改。

由主线程启动真实集成服务并安装 Chromium 后执行：

```bash
PATENTSAR_E2E_BASE_URL=http://127.0.0.1:18765 npm run e2e
```

测试不会启动/停止任何 HTTP 服务。基础验收包括 1672×942、1280×800、390×844 的工作台与环境管理，
真实会话、原始 PDF 上传、PNG/文本切换、页码、缩放与刷新。默认真实 PDF 为
`/srv/wsl/data/patentsar/inputs/WO2025264818-PAMPH-20251226-0041.pdf`，可用 `PATENTSAR_E2E_PDF` 覆盖。
文件不存在时上传测试显式跳过；上传会保留专用测试项目，不删除其他项目数据。

在独立测试状态库中按需指定这些参数；未指定的业务路径会显式跳过，不能记作通过：

- `PATENTSAR_E2E_HISTORY_PROJECT_ID`：已导入真实业务产物的专用测试项目；执行分页、复核持久化和导出。
  会写入复核注记，因此不能无授权指向用户正在复核的项目。
- `PATENTSAR_E2E_RUN_JOBS=1`：允许在本次上传的项目中启动、取消真实提取进程。
- `PATENTSAR_E2E_FAILED_JOB_ID`：真实失败任务，验证失败阶段/错误没有被升级成成功。
- `PATENTSAR_E2E_OUTPUT_DIR`：默认 `/srv/wsl/tmp/x-patentsar-ui-e2e`，所有 trace/截图留在 E 盘外部产物目录。
- `PATENTSAR_E2E_SOURCE_PROJECT_ID`：附有真实原文和来源结构的项目，进行只读页图/标注比例验证。
- `PATENTSAR_E2E_UNAVAILABLE_HISTORY_JOB_ID`：真实 history_available=false 的旧任务；只读检查不会把共享目录阶段显示为本次成功。
- `PATENTSAR_E2E_PROGRESS_JOB_ID`：带真实 progress 的已结束任务；只读检查阶段观察与设备/缓存/RSS，不伪造进度。
- `PATENTSAR_E2E_RUN_ANALYSIS=1`：明确允许有界本地 CPU 分子推理；不可用或失败不记为通过。
- `PATENTSAR_E2E_ANALYSIS_COMPOUND_ID`：专用历史项目中可用的真实结构裁图标识。
- `PATENTSAR_E2E_ENV_OPERATIONS=1`：在独占 QA 环境状态中进行安装工具的真实轻量检测，验证持久化历史与刷新；不安装软件或下载模型。

环境管理的三视口读取/确认测试默认执行，要求真实环境 API，不拦截或补造目录。
组合与单组件安装必须确认目录、CPU 下载范围和服务端许可证，默认不选中。
安装选择仅按服务端组件的 `dependencies` 递归展开，最多六项，拒绝未知/缺失、重复、自依赖或循环依赖。
确认弹窗逐项列出完整执行集合的版本、下载大小和许可证，包括 SDK 与已 ready 的前置组件；未报告大小不视为零。
同一展开集合进入持久化请求和 POST；inspect 保持原始选择，不隐式扩展。操作响应不接受额外未确认组件，
已完成组件仍必须属于执行集合，不能放宽校验来掩盖后端计划不一致。
手机抽屉位于 header 下方，44×44 导航开关始终可点击；打开时仅正文与其他 header 控件 inert，
保留第二次点击、Enter 开启、Escape 关闭和焦点恢复。浏览器回归检查真实命中与可视边界，不使用 force click。
操作进度仅使用服务器阶段和已完成组件数，不预测百分比或剩余时间。后台操作不会随页面关闭而取消。
未知写入保存到本功能独立的会话恢复记录；刷新后先核对服务器，再以原请求 ID/参数显式重试。
选中的持久化操作 ID 保存在 `#/settings?operation=…`。损坏恢复记录也必须成功读取服务器历史后才能显式清除。
不得在 CI 中确认巨大模型安装；完整真实安装/激活验收由运营方在独立 E 盘环境完成。

桌面布局验收实际测量表格面积、原文宽度、拖动/键盘/刷新/全屏；手机检查
原文、表格、输入页和弹窗不溢出。布局保持在 hash，不依赖个人浏览器存储。

不并发安装浏览器；共享 Chromium 缓存由主线程管理。

`results-workspace.spec.ts` 是本次结果复核路径的只读真实服务回归：三个视口实际测量紧凑/舒适行高，
核对指标隐藏/恢复与选择保留、独立活性来源和原文刷新、原 crop/重绘 PNG 并排及人工统计。
重绘用例需要当前第一页有服务端实际提供 crop、canonical SMILES 和 redraw_image_url 的化合物；
没有这些真实前提会失败或按未提供项目参数显式跳过，不借用样例图片/API 拦截。
任务历史与进度用例需以上真实任务参数，未指定时显式跳过。测试与生成证据必须绑定本次实际部署版本。
Linux 门禁、格式归一化和构建在原生 Node 环境运行；Windows Node 或源码审阅不能替代这些证据。

## 依赖与许可证

npm 和 `package-lock.json` 是唯一前端依赖权威，直接依赖固定到精确版本。
生产仅 React、React DOM（MIT）和 Lucide React（ISC），没有 CDN 字体/图片或图片生成依赖。
Vite/Vitest、TypeScript、Testing Library、jsdom、Playwright、Prettier、Oxlint 为开发依赖。
Oxlint 为唯一 lint 工具（MIT），避免引入对当前 TypeScript 7 不兼容的 TypeScript-ESLint peer 链。
构建产物保留完整第三方许可；版本升级前运行 `npm audit` 与本包完整回归。

## 故障排查

- 无法连接 API：确认主线程服务端口，配置开发代理或直接打开生产同源地址；不扫描/终止其他项目。
- 401/403：重新加载本地会话；不要关闭 CSRF、改 cookie 或绕过服务端 origin 校验。
- 契约错误：检查 API 的 snake_case 响应与共享文档，向主线程报告，不补造默认业务数据。
- 页面图片不可用：检查是否历史导入、原 PDF 缺失或图片 404；不能把 OCR 文本渲染成“原始 PDF”。
- 409 复核冲突：载入最新版本，比较已保存注记，再明确提交保留的草稿。
- 运行禁用：查看 `/runtime` 展示的可用性并由运营方修复环境，前端不降级到模拟提取。
- 环境目录 404/契约错误：运行的后端尚未提供管理契约，页面保留错误和运行诊断，不返回演示组件。
- 环境写入结果未知：先“检查服务器状态”，不要更换请求 ID 盲目重放；等待中的后台操作可在历史中读取。
- 环境设置 409：刷新目录，比较新的配置版本后显式保留输入；前端不会自动覆盖他人修改。

第一方代码 Apache-2.0，详见仓库根 LICENSE；用户专利与第三方模型不因此变更许可。
