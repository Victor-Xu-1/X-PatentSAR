# X-PatentSAR 前端

单一 React / TypeScript 工作台，产品版本 v0.1.0 来自 /api/v1/health。
前端只消费 [API v1](../docs/WEB_API.md)，不另建提取或预测引擎。
默认只做 PDF → 完整结构/活性表 → 在线修正；说明和技术信息按需打开。
系统字体、白/浅灰背景和黑色操作按钮使用唯一样式权威 src/styles/tokens.css。
Evidence Studio 将真实 PDF 和完整表格作为视觉中心，不使用生成图代替科学证据。
默认原文栏宽 34%，显式 URL 栏宽不改变；手机结构列随表横向滚动，编号与修正保留。
数据表头整体可打开列菜单，右侧独立窄边用于调整列宽。选择列只保留勾选框，
隐藏/恢复仍从“列设置”完成；不显示没有用途的列菜单。
筛选弹层与全屏共用可见焦点边界，Tab/Shift+Tab 循环，Esc 返回触发入口。
PDF 和表格的程序化定位共用系统减少动态效果偏好，不新建动画或轮询链路。

## 开发与构建

在 E 盘 WSL 工作树的 frontend 内使用 Linux Node 24.21.0：

```bash
export PATH=/srv/wsl/envs/node-v24.21.0-linux-x64/bin:$PATH
export npm_config_cache=/srv/wsl/cache/npm
export TMPDIR=/srv/wsl/tmp
export PLAYWRIGHT_BROWSERS_PATH=/srv/wsl/cache/ms-playwright
export NODE_OPTIONS=--max-old-space-size=768
npm ci --ignore-scripts
PATENTSAR_API_PROXY_TARGET=http://127.0.0.1:18765 npm run dev
```

Vite 仅监听 loopback 5173；代理只接受 loopback HTTP origin。8765/8766
可能属于其他软件，不启动或停止它们。生产请求始终同源 /api/v1，无前端密钥、
CDN 或外部转换服务。不得把秘密放入 VITE_*。

按具体修改选择回归及直接消费者，不执行未经授权的全局测试。例如结构/数值编辑：

```bash
npx vitest run tests/corrections.test.tsx tests/manual-properties.test.tsx tests/structure-editor-contract.test.ts --maxWorkers=1 --pool=forks
npm run typecheck
npm run build
```

对改动文件执行 Oxlint/Prettier。忽略的 dist 含 index.html、ketcher.html、
哈希资源、Indigo worker/WASM 和 THIRD_PARTY_LICENSES.md，不提交编译产物。
控制方 tools/build_frontend.py 验证资产并打入同一 wheel；Node 仅用于构建。
生产不能通过 file:// 打开。构建预览不代理 API，不能代替集成验证。

## 交互与模块

- features/workspace：左 PDF、右表格，精简页眉。真实进度仍用单一作业读取链路。
- model/workflowGroups + features/jobs：只将相邻真实阶段归为四个概览组，保留记录
  顺序、失败及未知状态。完整 StageList 是唯一阶段明细；Esc/点击外部关闭浮层。
  单阶段分析任务不显示重复概览。不能以分组、颜色或已处理总量替代验收结论。
- features/results：独立活动列、Excel 式列隐藏/筛选/排序/宽度、冻结编号/结构、
  复制/导出，以及唯一修正窗口。
- features/structure-editor：本地 Ketcher 3.18.0 独立 frame，隔离 CSS/弹窗；
  同源、窗口绑定、限长消息协议，单个串行去抖导出。无全局 SDK 入口。
- model/propertyValues：手工值优先于当前模型值；显式留空不借用预测。
- api：DTO 校验、会话/CSRF、超时和有界响应；写入不自动重放。
- features/tasks / environment：真实上传、持久队列与唯一环境管理页面。
  配置/安装边界见 [运营文档](../docs/OPERATIONS.md)。
- tests / e2e：隔离状态测试、真实服务 Playwright，不使用生产假数据或拦截成功。

页面样式各有单一模块（workflow / tasks / management / environment / analysis），
共享弹窗为固定标题、滚动正文及可达的操作区。环境页只显示真实总体就绪、一次完整
安装与当前进度；路径在独立对话框中修改。技术详情按需打开，不永久展示日志。

历史删除采用共用确认/恢复模块：最近文件、任务、已生成文件和环境操作记录各有
删除入口。回收站按需打开，不成为常驻仪表盘。服务器确认记录决定能否删除/恢复；
运行中或进程清理未核实的记录不能删除。明确提示文件保留、未释放磁盘空间。
只删任务记录不清空当前结构/指标或原始 QA。网络中断后的写入结果未知须先刷新，
不能自动重试。子记录先恢复所属项目；环境历史删除不卸载组件。契约见 API 文档。

点击活性数值直接跳原文并圈出有证据的单元格；不显示重复页码徽标。
未证明精确框时只定位页，不能画猜测框。首次默认页来自实际 first_structure_page，
显式页码/跳转和布局/筛选通过 hash 刷新恢复。

修正只包含编号、画结构、各列活性、六项指标和保存/取消。
延迟读取的修正表单在输入框可用时聚焦；用户已进行键盘、指针或焦点操作时不抢回焦点。
初始焦点观察在成功、用户操作或关闭时立即释放，不使用定时重试。
Ctrl/Cmd+S 调用同一保存，不打开独立的 Ketcher 文件导出。
原图无框并适度放大；原图和 RDKit 派生图仍有不同证据含义。
原 PDF、裁图、正式产物和 QA 不覆盖；有效源指纹和修订 CAS 保留审计。
图改变才自动重算该化合物；坐标、编号或数值改变不重跑模型/PDF。
既有活动实验/来源元数据保留，空缺实验列可填值但不伪造原文页。

Ketcher 按需加载。SMILES 与 V3000 顺序导出，避免 SDK 按输入而非格式关联回复
引发串格式。关闭即退订；导出超时/无效数据禁用保存，明确重载保留最后成功结构
及数值草稿。后端 RDKit 检查图、手性、同位素、电荷、盐和 MDL 边界；
不接受查询/未知原子、相对增强手性或结构与 SMILES 不一致。

## 真实浏览器验证

必须使用项目 Chromium/Playwright，不能以源码、mock、健康接口或内置浏览器
截图替代绘图/持久化证据。只读三个视口：

```bash
PATENTSAR_E2E_BASE_URL=http://127.0.0.1:18765 \
PATENTSAR_E2E_SOURCE_PROJECT_ID=explicit-approved-project \
PATENTSAR_E2E_OUTPUT_DIR=/srv/wsl/data/patentsar/verification-ui \
npx playwright test e2e/direct-edit.spec.ts --grep 'minimal drawing'
```

测试不启停服务。写入测试要求独立复制状态及
PATENTSAR_E2E_ALLOW_CORRECTION=isolated-state，不能指向用户生产复核项目。
simple-workbench.spec.ts 的 online edits persist 用真实工具画受控乙醇参考、
保存五列活动/六项数值、重开、实际本地 ADMET 和导出；这不证明专利 OCSR 图准确。
可指定 PATENTSAR_E2E_EDIT_COMPOUND_ID 或 PATENTSAR_E2E_EDIT_DISPLAY_ID。
化学往返测试通过编辑器公开消息边界提供明确参考、真实整理绘图和导出，
不写入专利结果。未提供必需参数的测试为跳过，不能算通过。
所有 trace/截图/验证产物放 E 盘外部证据目录；不用全套场景代替范围选择。

## 依赖与排错

npm + package-lock.json 是唯一锁，直接依赖精确固定。React/React DOM、
Paper core、events 为 MIT，Lucide 为 ISC，Ketcher/Indigo 为 Apache-2.0。
3D/宏分子/识图/额外文件保存等工具默认关闭；不加入第二个 editor 服务。
锁中 upstream 可选 3D peer 的 React 18 提示不代表启用了 3D；
升级需审阅 peer、冻结安装、生产依赖 audit 和实际绘图回归。
首方 Apache-2.0 不覆盖用户专利或科学环境上游许可，完整 attribution 随 wheel。

- 401/403：重建本地会话；不要关闭 Origin/CSRF。
- 409：保留草稿，读取当前修订后再明确保存。
- 未知写入结果：先核对服务器，不重复提交或换请求身份。
- 编辑器错误：检查同源 ketcher.html、worker、WASM、限于这两处的 WASM CSP。
  不允许 JavaScript unsafe-eval，也不切换外部转换服务。
- 缺图/缺模型值：显示实际缺失/失败；不以 OCR 文本、原图或假值替代。
