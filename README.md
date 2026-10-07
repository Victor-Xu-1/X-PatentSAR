# X-PatentSAR

开源仓库：[Victor-Xu-1/X-PatentSAR](https://github.com/Victor-Xu-1/X-PatentSAR)。
软件与仓库的对外名称统一为 **X-PatentSAR**；Python 发行包与 CLI 使用规范化技术标识
`x-patentsar`。第一方源码采用 Apache-2.0，第三方许可和模型边界见 `NOTICE`。

独立运行的专利化学结构、活性数据与结构—活性关系（SAR）提取软件。当前生产适配器面向 WIPO 专利 PDF，主链为：

```text
classify -> locate -> structures -> bind -> activity -> smiles -> final -> qa
```

软件默认 fail closed：结构绑定、SMILES 或最终 QA 未满足严格规则时，命令以失败状态结束，结果不能作为正式交付。`--allow-partial` 仅保留人工复核材料，不代表验收通过。

## 支持范围

- 运行平台：Linux / WSL2；当前版本在 Ubuntu WSL2 验证。
- 主程序：CPython 3.12。
- OCSR：生产主链仅接受 DECIMER；RDKit 负责 SMILES 校验与标准化。
- LLM/VLM：仅用于可选的活性表复核和建议性 QA；生产页面分类为确定性规则，模型不能改变正式验收。

专利版式通过原文证据解析，不使用专利号、固定页码或化合物清单做特殊适配。
标题支持段落号和常见制备/合成前缀；独立标题结构与后续步骤结构分别校验。
结构表按原始表头确定编号与结构列，可有任意受限数量的附加列，二者不必相邻。
活性表保留多行表头、单位、每个物理列及原始读数，未知/同名列不会覆盖彼此。
网格 OCR 不自动倒转单个数字；原始 NA/ND/NT、比较符号、单位和不确定性保留。
无法证明的编号、混合结构或冲突读数仍需复核，不能承诺任意低质量原文百分之百自动正确。

### 可选局部证据 LLM 接口

本局部证据接口默认关闭，不调用云模型、不外发原文。本地识别/指标模型照常运行；
原有独立建议性 QA 仍按其自身开关执行，Web 默认跳过该项。运营方配置 HTTPS LLM 接口并明确同意
发送局部证据后，可设置 `PATENTSAR_LLM_RESOLUTION_MODE=on-error` 或 `quality`，同时设置
`PATENTSAR_LLM_RESOLUTION_DATA_CONSENT=true`。前者仅在确定性提取出现证据问题时复核，
后者额外检查有限的原始列映射。使用现有 LLM 客户端和缓存，不启动常驻模型服务。
当前链路在绑定/活性提取后、识别前统一执行一次局部列证据复核；接口还定义了受限的
标题归属和表头候选协议，尚不自动把这两类模型建议升级为正式绑定。

只发送有边界的表头文字和对应位置，不发送整份 PDF、分子图、SMILES 或全部数据行。
同一列去重，一次任务共用一个预算：默认最多八次 HTTP 尝试，串行，30 秒请求超时、
零重试、12,000 输入字符及1,024输出 token。结构化响应只允许选择已有候选和证据引用；
缺失引用、无效响应、预算耗尽和模型弃答均明确记录，不补值、不改手性、不放宽 QA。
缓存身份包含原文、证据、协议、模型、服务和响应约束，不包含新运行的任务编号。
结果独立保存为 `evidence_resolution_review.json`，原始列和严格验收不变。
这是一套可配置、受验证边界约束的接口，不是已经完成真实云模型科学验收的兜底承诺。
- 交付物：Excel、SDF、结构裁图、带身份信封的绑定/SMILES JSON、流水线摘要与 `final_qa_report.json`；可选模型建议写入独立的 `llm_qa_report.json`。

独立版不依赖 Synon 后端、插件 manifest 或 `.synon` 目录。

## Web 工作台

工作台默认只有一件事：上传 PDF，得到结构—活性表，并可在线修正。
界面采用简洁的生物医药工作台视觉：白色内容、冷浅灰背景、近黑操作与系统无衬线字体，
薄荷绿仅用于少量图标、导航和真实状态；次要操作按需展开。保留独立橙色标志，
不复制第三方字体或商标。原文与表格仍是主工作区；修正窗口在宽屏并列展示本地绘图
与编号/列数值，窄屏顺序排列，不增加说明模块或改变提取、保存与验收规则。
Evidence Studio 视图使用统一字号、留白与细分隔线，默认原文占可调分栏的 34%。
流程默认展示四个只读概览组及真实当前状态，完整阶段、计数与资源观测按需打开；
分组只合并相邻显示项，不重排记录或改变执行链。上传、最近文件、任务、环境和
证据摘要沿用同一视觉系统，不加入营销插图或额外仪表盘。
`#/new-task` 是默认入口：选择原始 PDF 后点击“开始提取”，软件通过同一个
持久任务先完成严格八阶段提取，释放识别模型后自动计算六项指标。任务名称从
文件名推断；上传页只保留 PDF 和开始提取，不再提供高级选项或隐藏的元数据输入。
新上传沿用安全默认参数：不强制重算、不包含中间体、任务说明为空；完整 ADMET 链路不变。

任务流程条按真实执行关系显示：**文档解析 → 结构定位 → 结构分割 → 编号绑定 → 活性提取 →
SMILES 识别 → 生成结果 → 核心校验 → ADMET / 指标**。前八步对应唯一 CLI 主链；
末步是同一任务在原识别进程释放后的后置研究阶段，不是第九个正式提取阶段。
正式完成仍要求核心 QA 通过。完整执行后被 QA 拒绝的运行可保留合格记录的研究指标，
但任务仍为失败 / 需复核；技术故障或不完整执行不进入这条后置链路。
配置了 `include_admet=true` 的任务从开始就显示此计划步骤；未启动时只显示等待或未执行，
不会借用旧失败标记、模型计数或资源观察。实际补齐缺失结构时显示“结构补齐”，计算六项
指标时显示“指标计算”。仅补齐/修正触发的分析任务不显示未执行的八个核心步骤。
MW、LogP、TPSA、HBD、HBA 由独立 RDKit 计算并保存，LogS 为 ADMET 预测；
模型等待或失败不清空已完成的五项计算。两类都不是专利实测。

流程条区分处理总量与失败/待复核数。完整运行后被核心 QA 拒绝时，摘要仅使用完整、
一致的识别进度记录显示待复核结构数，不把 `已处理 N/N` 写成 `失败 N`；缺少可靠计数
时只显示需复核。识别、导出和 QA 的原始失败状态保持不变，已运行到 QA 的任务不再
被描述为在识别阶段停止。验收详情按明确编号聚合重复上报，保留各项不同原因及来源
阶段；其他校验信息独立保留。这是只读展示，不改变正式验收、模型观察或原始产物。

任务因服务或系统中断后，重新打开软件会安全核对保存的任务进程，再提供**继续提取**。
旧进程与新系统里复用同一 PID 的进程不会混淆；未知、损坏或不同工作区的记录仍明确
禁止续跑。核对证据单独保留，不通过删除记录来绕过保护。
续跑不需要重新上传 PDF：使用同一原文的合格 OCR、完成阶段、已完成分割批次和精确
识别原始缓存，从尚未完成的部分继续。每次续跑创建独立运行目录，保留旧结果和历史；
不继承旧 QA、人工修订或预测作为新的验收。检查点准备也可中断、取消并再次续跑，
准备完成前不会启动提取。软件不自动循环重试、不降低严格验收，也不停止其他软件腾资源。

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
Compound 编号、结构和行末修正入口固定；手机上结构列参与横向滚动，以保留活动值的
可见空间，编号、选择与修正入口仍固定。编号与结构各自可调整宽度。
每列边界可鼠标拖动或键盘调整宽度。
点击数据表头可打开列菜单，右侧窄边界专用于调整列宽；选择框不再叠加无效菜单，
可从“列设置”隐藏。列菜单直接显示 Excel 式搜索、取值勾选、全选及“空白”，按“确定”
才应用，“取消”/Esc/点击外部不改变表格。搜索只查找菜单取值，不自动改动勾选。
全屏下菜单保持可见，Tab/Shift+Tab 在菜单内循环，Esc 返回原表头。
PDF 来源定位与表格跳转遵循系统“减少动态效果”设置。
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

### 自动 Lead 候选

默认 Web 任务在六项指标完成、模型进程释放后，用同一个研究任务自动评估
完整化合物集合并标记约 5–10 个 Lead 候选（目标 8 个）。独立 `Lead` 列
支持隐藏、列筛选、排序、复制及 CSV/JSON 导出；提示中保留得分依据和局限。
不改变 Compound 的默认自然排序，不新增常驻服务或模型。无活性记录仍完整
保留结构、SMILES 和指标，但缺少有效活性证据时不能成为 Lead。

策略是可复现的研究优先级启发式：逐个精确实验列比较活性、计算全项目覆盖度，
再综合 ADMET 风险、六项理化指标、来源/结构质量与化学空间多样性。未知方向、
未知单位、删失/区间读数和冲突观察不被猜成强活性。只选择有当前合格结构
与足够可用证据的候选，不为凑数填入缺数据、未确认编号或被拒绝的结构。

ADMET 使用现有 pinned ADMET-AI 的 hERG、AMES、DILI、ClinTox、五个 CYP
抑制概率、HIA 和口服生物利用度概率；不重复推理、不把缺失当安全、不使用
物理范围异常的清除率/分布容积。已有仅六指标的观察仍可读，软件在研究任务
中从经验证的全端点缓存补齐风险证据，缓存缺失时才调用现有模型。口服理化
性质是软偏好，不是对大分子/PROTAC 的通用淘汰标准。

Lead 是候选推荐，不是实测、实验验证、安全证明或正式 QA 升级；未知选择性、
体内 PK、合成可行性和模型适用域不能凭空补出。规则来自实际每个任务的输入，
不包含固定专利号、页码或候选清单。数据或分子图变化使旧候选失效；数值修正
只重新评估轻量选择，图修正沿现有单一指标任务完成后再评估整个项目。
筛选/翻页/隐藏列不改变候选。原 PDF、生成产物、审计和 QA 保持不变。

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
“未关联活性”不表示阴性或没有活性。正式绑定、OCSR、导出和严格 QA 统一覆盖
有原文编号证据的结构目录，不以活性集合裁剪；同一个 OCSR 批次识别这些结构，使用
完全相同的原图、DECIMER、RDKit 和手性风险校验。合格结构都进入同一六指标
计算入口，不检查是否有活性数据；编号、原图、SMILES、重绘、来源及修正能力
采用相同标准。未确认编号、缺图或识别失败仍保留原图/定位和明确状态，不能
猜测归属或计算值。SMILES v2 的 `records` 保留已确认编号结构的统一顺序；
活动缺失、候选编号和历史观察不会被猜测为已确认数据。旧产物不改写。已有项目用“补齐结构与指标”，由软件
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
保持原始产物的契约和验收范围，不能借人工修正或指标计算升级原始 QA。
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

**存储位置**中可修改集成环境安装目录、上传文件目录和生成结果目录，三项一次保存。
上传和结果目录必须是允许范围内可写的 Linux 私有目录；存在未知内容、符号链接、
路径重叠或并发版本冲突时拒绝保存，不改权限、不覆盖文件。结果目录包含新任务的
运行产物，以及新生成的 CSV/JSON 导出副本；浏览器下载副本的“另存为”位置仍由浏览器控制。
修改仅影响后续新上传、新任务/续跑和新安装。旧原文、旧结果、旧运行规格和审核记录不搬动，
历史根目录持续登记，原文显示、结构来源和续跑仍使用原来的真实位置。
本机 E 盘允许数据根为 `/srv/wsl/data/patentsar`，由仓库外入口的
`PATENTSAR_DATA_ALLOWED_ROOT` 配置；其他部署默认使用 Web 状态目录的父目录。
工作区数据库、审计、控制日志与缓存保持固定管理位置，不因修改文件目录而迁移。

顶栏直接显示的 **环境管理**（`#/settings`）以完整环境状态和**一键部署全部环境**为主入口。
软件安装并启动后，一次确认即可建立一个完整后台任务，自动处理安装工具、基础 PDF/OCR/RDKit、
DECIMER、受限本地手性兜底和 ADMET 的运行环境与模型。用户不需要逐项安装或手工拼装路径。
后端先真实检查已有组件，合格的直接复用，缺失或不兼容的安装到新私有前缀；八个组件全部通过
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
export PATENTSAR_DATA_ALLOWED_ROOT=/srv/wsl/data/patentsar
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

`run` 是唯一正式交付链路。`classify`、`activity`、`smiles`、`qa` 用于阶段级复跑或检查；`excerpt`、`validate`、`score` 是诊断工具。旧式独立 `profile`/`bind`/`truncate` 命令已移除，避免绕过原文编号、结构归属和统一验收。`excerpt` 仅供人工复核，正式链路始终使用原始 PDF 坐标。

## 版本与数据契约

- 产品版本：`0.1.0`，遵循 Semantic Versioning。
- 流水线契约：`patentsar.structure-led` `3.0.0`。
- 准确性规则集：`patentsar.accuracy-first` `2.1.1`；产品仍为 `v0.1.0`。
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
嵌入同一个绑定产物；绑定实现指纹为 8，产品仍是 v0.1.0。表外结构须有
完整的原文图下注释与唯一空间归属，`8A` 等后缀不会退化成父编号。
全部结构编号已有确定的原文空间证据时，软件跳过通用多轮补漏，而不是
重复裁图 OCR。运行中已完成的检查点会展示为候选结果，正式通过仍以最终 QA
为准；切换到新运行会自动清除上一轮的界面结果。

正式 OCSR 主模型只保存和校验 DECIMER 的原始字符串，不再猜测元素字母、修环编号、
删原子/片段、补同位素或根据编号翻转手性。非干净预测可对同一截图做一次
有记录的图像标准化重试；仍不合格则保留原始候选并严格停止，不能修改字符串
凑出可导出的分子。模型原始观察使用独立缓存版本，旧自动修补缓存不会被提升
为新版正式结果。

主模型退出后，软件可对最多八条“手性标记未保留”的记录执行受限本地 MolScribe 兜底。
候选必须有完全相同的非手性连接图（含键级、同位素、电荷和盐片段），恢复原始标记并保留
主模型已有手性；所有剩余原子对应均须一致。原图当前风险检查和对照证明同样参与导出、
QA 与研究计算。普通结果不再识别一次；波浪/未知键、连接图变化或冲突仍需复核。
模型固定 CPU、两线程，不常驻、不与主模型并行，也不调用外部 LLM。运行环境与权重在
一键环境部署中统一安装。已装好/模型可加载不等于识别准确性或实验验收。

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
uv run python tools/build_wheel.py --work-root /srv/wsl/tmp --out-dir dist
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

GitHub CI 不执行全量发现测试。每个 PR 必须更新 `.github/verification_scope.json`，
明确基线 SHA、完整改动路径及直接相关的 Python / Vitest / Playwright 范围；
范围与提交差异不一致会失败，不会回退成全量测试。空前端或浏览器范围不启动测试引擎。
构建、环境资源一致性和 wheel 审计仍执行。真实专利与原生编辑器的私有浏览器验收
在 E 盘保存，不把专利输入或本地会话资料上传到 CI。

统一构建器从当前 Git 管理的包源码和已校验前端清单创建全新临时源目录，
不复用或清理历史 `build`。轮子审计逐文件校验当前源码清单与 SHA-256，
拒绝多余旧模块、缺失文件和旧内容。每次构建使用新的输出目录；WSL 的工作目录
保持在 E 盘对应的 `/srv/wsl/tmp`，CI 使用运行器自己的临时目录。

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
