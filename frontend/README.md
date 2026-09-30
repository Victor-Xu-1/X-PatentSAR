# X-PatentSAR 前端

单一 React / TypeScript 工作台，仅调用控制方维护的 `docs/WEB_API.md` v1 API。
没有生产演示数据、请求失败回退、第二套提取引擎、ADMET 预测或智能摘要实现。
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
- `src/model`：刷新可复现的 hash 路由、来源展示与 PDF 上传校验。
- `src/hooks`：中止过期读取、错误可见的加载状态、仅活跃任务轮询、搜索防抖。
- `src/components`：导航、语义化反馈、键盘 tabs、原生 modal dialog、受限同源图片。
- `src/features`：工作区、PDF 视图、真实结果、项目、任务与只读运行环境。
- `src/styles`：按布局、PDF、表格、管理页、对话框与视口拆分。
- `tests`：隔离契约输入和行为测试；不会进入生产打包。
- `e2e`：真实服务的 Playwright 验收，没有拦截 API 或 seed 路由。

## 数据与操作边界

页面原图、裁图、文本、标注、统计和任务阶段都来自 API。历史结果保留来源提示，缺失原始
PDF 时不制造页面。活性值原样展示，等级值不会强行改成 IC50。置信度缺少数值时显示未知/无数值。
人工复核使用 `expected_revision`，409 后保留草稿，要求显式读取最新版本再保存；永不改变核心 QA。

服务端支持关键词、靶点、置信度、复核状态和分页。现有 API 未提供 metric 查询参数，
“显示活性指标”只控制每个化合物行内的指标展示，不改变服务端化合物总数。
选择跨结果页保留，修改搜索/筛选会清空选择。导出选择明确发送真实 IDs；“全部结果”发送空 IDs，
明确不受当前表格筛选限制。“当前筛选结果”通过既有 export 端点的 q/confidence/review/target
查询参数导出所有匹配页，不发送分页参数，不把当前页当作全部匹配结果。未接受的项目始终提示仅供复核。

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

测试不会启动/停止任何 HTTP 服务。基础验收包括 1672×942、1280×800、390×844 的工作台与运行环境，
真实会话、原始 PDF 上传、PNG/文本切换、页码、缩放与刷新。默认真实 PDF 为
`/srv/wsl/data/patentsar/inputs/WO2025264818-PAMPH-20251226-0041.pdf`，可用 `PATENTSAR_E2E_PDF` 覆盖。
文件不存在时上传测试显式跳过；上传会保留专用测试项目，不删除其他项目数据。

在独立测试状态库中按需指定这些参数；未指定的业务路径会显式跳过，不能记作通过：

- `PATENTSAR_E2E_HISTORY_PROJECT_ID`：已导入真实业务产物的专用测试项目；执行分页、复核持久化和导出。
  会写入复核注记，因此不能无授权指向用户正在复核的项目。
- `PATENTSAR_E2E_RUN_JOBS=1`：允许在本次上传的项目中启动、取消真实提取进程。
- `PATENTSAR_E2E_FAILED_JOB_ID`：真实失败任务，验证失败阶段/错误没有被升级成成功。
- `PATENTSAR_E2E_OUTPUT_DIR`：默认 `/srv/wsl/tmp/x-patentsar-ui-e2e`，所有 trace/截图留在 E 盘外部产物目录。

不并发安装浏览器；共享 Chromium 缓存由主线程管理。

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

第一方代码 Apache-2.0，详见仓库根 LICENSE；用户专利与第三方模型不因此变更许可。
