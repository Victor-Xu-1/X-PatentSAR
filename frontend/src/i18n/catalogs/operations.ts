/** Runtime, task and history interface messages. */
export const operations: Record<string, string> = {
  // Jobs, recorded stages and observations.
  '任务操作失败。': 'The task operation failed.',
  取消任务: 'Cancel task',
  继续提取: 'Resume extraction',
  请先选择项目: 'Select a project first',
  '请先补充原始 PDF': 'Add the original PDF first',
  运行环境未就绪: 'The runtime is not ready',
  '运行现有核心提取链，不调用付费建议模型':
    'Run the core extraction pipeline without paid advisory models',
  '正在提交…': 'Submitting…',
  运行提取: 'Run extraction',
  任务详情: 'Task details',
  'API 待核对，查看任务详情': 'API needs attention; view task details',
  'API 待核对': 'API needs attention',
  '取消当前提取任务？': 'Cancel the current extraction task?',
  '仅取消此项目的当前任务。已保存的结果与缓存不被删除，是否可恢复以服务端真实状态为准。':
    'Cancel only this project’s current task. Saved results and caches are retained; the server determines whether it can be resumed.',
  继续运行: 'Keep running',
  '正在取消…': 'Cancelling…',
  确认取消此任务: 'Confirm cancellation',
  创建: 'Created',
  开始: 'Started',
  结束: 'Finished',
  失败详情: 'Failure details',
  已保存的任务参数: 'Saved task parameters',
  包含中间体: 'Include intermediates',
  强制重算: 'Force recomputation',
  '运营备注（不执行）': 'Operator note (not executed)',
  '续跑保留原备注及中间体选项，不强制重算。':
    'Resume retains the original note and intermediate options without forcing recomputation.',
  '任务 {id}': 'Task {id}',
  筛选任务所属项目: 'Filter tasks by project',
  全部项目: 'All projects',
  全部记录: 'All records',
  回收站: 'Trash',
  刷新任务记录: 'Refresh task records',
  '正在读取任务记录…': 'Loading task records…',
  尚无提取任务: 'No extraction tasks yet',
  '上传 PDF 开始，或从最近文件打开已有结果。':
    'Upload a PDF to begin, or open existing results from Recent files.',
  提取任务记录: 'Extraction task records',
  打开关联文件: 'Open linked file',
  创建时间: 'Created at',
  全部任务记录: 'All task records',
  任务运行链路: 'Task pipeline',
  待复核: 'Pending review',
  失败: 'Failed',
  '数量 {count}': 'Count {count}',
  ' · {context}；MW、LogP、TPSA、HBD、HBA 计算，LogS 为 ADMET 预测':
    ' · {context}; MW, LogP, TPSA, HBD and HBA are calculated; LogS is an ADMET prediction',
  补齐已证实来源的结构与指标: 'Complete structures and properties from verified sources',
  核心校验后执行: 'Runs after core validation',
  '来源区域 {regions} · 待修复 {unresolved}': 'Source regions {regions} · Unresolved {unresolved}',
  '所需内存 {required} MB · 可用 {available} MB':
    'Memory required {required} MB · Available {available} MB',
  '已等待 {seconds} 秒': 'Waited {seconds} seconds',
  进度未提供: 'Progress not reported',
  '复用 {pages} 页': 'Reused {pages} pages',
  '缓存命中 {hits} · {finding} {failures}': 'Cache hits {hits} · {finding} {failures}',
  执行设备未知: 'Execution device unknown',
  '峰值 RSS 未提供': 'Peak RSS not reported',
  '峰值 RSS {rss} MB': 'Peak RSS {rss} MB',
  检查点复用未知: 'Checkpoint reuse unknown',
  复用检查点: 'Reused checkpoint',
  '阶段记录数量 {count}': 'Recorded stage count {count}',
  '未计算 {count}（缺少有效SMILES）': 'Not calculated: {count} (no valid SMILES)',
  '本次执行，未复用检查点': 'Executed in this attempt; no checkpoint reused',
  '只展示服务端观察，不推算准确率、百分比或剩余时间。':
    'Server observations only; no inferred accuracy, percentage or time remaining.',
  '历史阶段不可用：本次任务的阶段记录无法可靠读取。':
    'Stage history unavailable: this task’s stage records could not be read reliably.',
  历史阶段可用性未知: 'Stage history availability unknown',
  尚未启动: 'Not started',
  历史阶段不可用: 'Stage history unavailable',
  阶段状态未知: 'Stage status unknown',
  '{label} · 未计算': '{label} · Not calculated',
  提取阶段详情: 'Extraction stage details',
  '{count} 条结构': 'Structures: {count}',
  任务流程: 'Task workflow',
  阶段分组: 'Stage groups',
  文档解析: 'Document parsing',
  活性提取: 'Activity extraction',
  结构定位: 'Structure location',
  结构分割: 'Structure segmentation',
  编号绑定: 'Identifier binding',
  'SMILES 识别': 'SMILES recognition',
  生成结果: 'Result generation',
  核心校验: 'Core validation',
  'ADMET / 指标': 'ADMET / Properties',
  等待: 'Waiting',
  进行中: 'In progress',
  完成: 'Complete',
  无数据: 'No data',
  有警告: 'Warnings',
  排队中: 'Queued',
  运行中: 'Running',
  运行完成: 'Run complete',
  运行失败: 'Run failed',
  已取消: 'Cancelled',
  已中断: 'Interrupted',
  需复核: 'Needs review',
  尚未验收: 'Not yet assessed',
  '核心 QA 通过': 'Core QA passed',
  提取未通过验收: 'Extraction not accepted',
  '历史结果 · 仅供复核': 'Historical results · Review only',
  高: 'High',
  中: 'Medium',
  待核验: 'Needs verification',
  复核通过: 'Review approved',
  复核不通过: 'Review rejected',
  值未提供: 'Value not provided',
  活性: 'Activity',
  '已处理 {completed} / {total} 页': 'Processed {completed} / {total} pages',
  '{completed} / {total} 页': '{completed} / {total} pages',
  '已处理 {completed} / {total}': 'Processed {completed} / {total}',
  '核心校验未通过，结果需复核。': 'Core validation failed; results need review.',
  '核心校验未通过，{count} 条结构需复核。':
    'Core validation failed. Structures requiring review: {count}.',
  '任务已中断，可继续提取。': 'The task was interrupted and can be resumed.',
  '任务已中断，恢复状态见任务详情。':
    'The task was interrupted; see task details for recovery status.',
  '运行失败，原因见任务详情。': 'The run failed; see task details for the reason.',
  '运行失败，服务端未提供原因。': 'The run failed; the server did not provide a reason.',
  '任务报告了错误，原因见任务详情。':
    'The task reported an error; see task details for the reason.',
  '历史阶段不可用。': 'Stage history unavailable.',
  '阶段状态未知。': 'Stage status unknown.',
  等待资源: 'Waiting for resources',
  解析定位: 'Parse & locate',
  结构编号: 'Structures & IDs',
  活性识别: 'Activity & recognition',
  校验与指标: 'Validation & properties',
  已完成: 'Completed',
  停止时未完成: 'Incomplete when stopped',
  状态未知: 'Status unknown',
  结构补齐: 'Structure completion',
  指标计算: 'Property calculation',
  'Lead 筛选': 'Lead prioritization',
  未执行: 'Not executed',
  状态未提供: 'Status not reported',
  停止时进行中: 'In progress when stopped',
  未通过验收: 'Not accepted',
  '{label}：{state}': '{label}: {state}',
  '{label}：{value}': '{label}: {value}',
  '；': '; ',
  '、': ', ',
  '{count} 项其他检查': 'Other checks: {count}',

  // Environment overview, details, storage and explicit consent.
  通过: 'Passed',
  未通过: 'Not passed',
  '尚未报告检查结果。': 'No check results reported yet.',
  '版本、来源与检查': 'Versions, sources & checks',
  目标版本: 'Target version',
  当前实测版本: 'Current detected version',
  未报告: 'Not reported',
  尚无当前检测: 'No current check',
  下载: 'Download',
  已占用: 'Disk usage',
  '前置依赖：': 'Prerequisites: ',
  '许可证：': 'License: ',
  服务端核定来源: 'Server-approved source',
  '来源：': 'Source: ',
  '尚无当前检查结果，请明确检测。': 'No current check results. Run an explicit check.',
  上次检测结果: 'Previous check results',
  '上次检测（已过期） · {status}': 'Previous check (stale) · {status}',
  '上次实测版本：': 'Previously detected version: ',
  '上次检测时间：': 'Previous check time: ',
  时间未知: 'Time unknown',
  环境组件库: 'Environment component library',
  组件库: 'Component library',
  '服务端尚未提供组件目录；不会展示演示环境。':
    'The server has not provided a component catalog; no demo environment is shown.',
  '{count} 项': '{count} items',
  已安装: 'Installed',
  先检测: 'Check first',
  安装: 'Install',
  修复: 'Repair',
  '目标：{version}': 'Target: {version}',
  '实测：{version}': 'Detected: {version}',
  '位置：{location}': 'Location: {location}',
  '检测时间：': 'Checked at: ',
  '未知（待检测）': 'Unknown (check pending)',
  '检测 {name}': 'Check {name}',
  检测: 'Check',
  '已通过当前检测，无需重复安装': 'Current checks passed; no reinstallation needed',
  '先检测组件状态，不重复安装已有组件':
    'Check the component first; do not reinstall existing components',
  '服务端不允许安装此组件，请检查原因':
    'The server does not allow this component to be installed; check the reason',
  '修复仍需确认完整依赖、下载范围及许可证':
    'Repair requires confirmation of all dependencies, downloads and licenses',
  '取消环境配置？': 'Cancel environment setup?',
  '只取消当前环境配置，不影响其他任务，已有环境会保留。':
    'Cancel only the current environment operation. Other tasks are unaffected and existing environments are retained.',
  '状态已变化，请关闭后重新确认。': 'The state has changed. Close and confirm again.',
  确认取消此环境操作: 'Confirm cancellation of this operation',
  存储位置: 'Storage locations',
  环境详情: 'Environment details',
  '完整部署计划无效。': 'The complete setup plan is invalid.',
  完整运行环境: 'Complete runtime environment',
  环境就绪状态: 'Environment readiness',
  '已就绪 {ready}/{total}': 'Ready {ready}/{total}',
  环境已就绪: 'Environment ready',
  一键部署全部环境: 'Set up complete environment',
  重新检测: 'Check again',
  检测全部组件: 'Check all components',
  'PDF 提取 · 结构识别 · 六项指标': 'PDF extraction · Structure recognition · Six properties',
  '完整部署暂不可用，请查看组件详情中的服务端限制或检测状态。':
    'Complete setup is unavailable. See component details for server restrictions or check status.',
  '{product} 环境管理': '{product} Environment',
  操作记录: 'Operation records',
  刷新环境目录: 'Refresh environment catalog',
  '当前后端未提供环境管理，请更新后端后重试。':
    'This backend does not provide environment management. Update it before retrying.',
  '正在读取真实环境组件目录…': 'Loading the environment component catalog…',
  '服务端未启用环境管理；网页不会执行替代安装。':
    'Environment management is disabled on the server; the page will not run an alternative installer.',
  环境操作记录: 'Environment operation records',
  '配置状态读取失败。': 'Could not read configuration status.',
  '正在读取配置状态…': 'Loading configuration status…',
  刷新状态: 'Refresh status',
  环境配置进度: 'Environment setup progress',
  等待配置环境: 'Waiting to set up the environment',
  等待检测环境: 'Waiting to check the environment',
  正在配置环境: 'Setting up the environment',
  正在检测环境: 'Checking the environment',
  取消此环境操作: 'Cancel this environment operation',
  环境操作已完成组件: 'Completed environment components',
  '上次配置未完成，现有环境已保留。':
    'The previous setup did not finish. Existing environments are retained.',
  '配置尚未应用，请重新检测或部署。':
    'The configuration has not been applied. Check or set it up again.',
  '状态读取失败，当前显示上次已知状态。': 'Could not read status; the last known state is shown.',
  刷新操作状态: 'Refresh operation status',
  确认完整环境部署: 'Confirm complete environment setup',
  确认环境安装: 'Confirm environment installation',
  安装位置: 'Installation location',
  '一次后台操作配置以下 CPU 组件，不安装 GPU / CUDA、不调用付费服务、不覆盖未知环境。':
    'One background operation sets up these CPU components. No GPU / CUDA installation, paid service calls or overwriting of unknown environments.',
  '包含完整运行环境及全部前置依赖。后端逐项复检并复用合格环境，仅安装缺失或不合格组件；检测错误会停止，不以重装掩盖。':
    'Includes the complete runtime and all prerequisites. The backend rechecks and reuses verified environments, installing only missing or unsuitable components. Check errors stop setup; they do not trigger reinstallation.',
  '包含所选组件及全部前置依赖；后端复检并复用合格环境。':
    'Includes the selected components and all prerequisites. The backend rechecks and reuses verified environments.',
  '下载按服务端报告展示，未报告不视为零，复用可减少下载。全部验证通过才应用配置，不改变已有任务或专利结果。':
    'Download sizes come from the server; unreported sizes are not zero. Reuse may reduce downloads. Configuration is applied only after all checks pass, without changing existing tasks or patent results.',
  环境安装计划: 'Environment installation plan',
  '已安装·已验证；后端复验后复用': 'Installed · Verified; rechecked before reuse',
  '目标版本 {version} · {role}': 'Target version {version} · {role}',
  所选组件: 'Selected component',
  前置依赖: 'Prerequisite',
  '下载：{size} · 许可证：{license}': 'Download: {size} · License: {license}',
  来源与位置: 'Sources & locations',
  '来源：{source}': 'Source: {source}',
  '现有位置：{location}': 'Existing location: {location}',
  '安装目录配置已变化，请关闭并重新确认。':
    'The installation location has changed. Close and confirm again.',
  '组件状态或依赖计划已变化，请关闭并重新确认；不重复安装已有组件。':
    'Component status or dependencies have changed. Close and confirm again; existing components are not reinstalled.',
  '服务端未提供完整许可证信息，不能确认安装。':
    'The server has not provided complete license information. Installation cannot be confirmed.',
  '我已确认安装目录、CPU 下载范围及上述许可证':
    'I confirm the installation location, CPU downloads and licenses above',
  '正在提交后台操作…': 'Submitting background operation…',
  确认下载并安装: 'Confirm download & installation',
  环境操作状态恢复: 'Environment operation recovery',
  配置状态待确认: 'Configuration status unconfirmed',
  '上次操作结果尚未确认，请先检查状态。不会自动重复安装。':
    'The previous operation’s result is unconfirmed. Check its status first; installation is not repeated automatically.',
  检查状态: 'Check status',
  重试原操作: 'Retry original operation',
  '仍未确认结果。重试将沿用原操作，不会创建重复任务。':
    'The result remains unconfirmed. Retry uses the original operation and does not create a duplicate task.',
  清除损坏的恢复记录: 'Clear damaged recovery record',
  '清除本功能的损坏恢复记录？': 'Clear this feature’s damaged recovery record?',
  '请先检查配置状态。只清除本页面的恢复信息，不停止后台任务或删除服务器记录。':
    'Check configuration status first. Only this page’s recovery information is cleared; background tasks and server records are retained.',
  保留记录: 'Keep record',
  '已核对状态，清除记录': 'Status checked; clear record',
  '存储位置保存失败。': 'Could not save storage locations.',
  '仅影响后续写入，不会移动已有文件。生成结果含提取产物及 CSV/JSON 导出副本；下载位置仍由浏览器设置。':
    'Applies only to future writes; existing files are not moved. Results include extraction artifacts and saved CSV/JSON exports. Download locations remain browser-controlled.',
  存储目录: 'Storage directories',
  '允许范围：{root}': 'Allowed root: {root}',
  '服务器配置已更新，未覆盖你的输入。当前存储位置：':
    'Server settings changed; your inputs were retained. Current storage locations:',
  使用最新版本并保留输入: 'Use latest revision; keep inputs',
  '保存中…': 'Saving…',
  集成环境安装目录: 'Managed environment directory',
  上传文件目录: 'Upload directory',
  生成结果目录: 'Results directory',
  '集成环境安装目录须位于服务端批准的本地目录范围 {root} 内，不能包含路径跳转、网络地址或命令。':
    'The managed environment directory must be within the server-approved root {root}, without path traversal, network addresses or commands.',
  '上传文件目录须位于服务端批准的本地目录范围 {root} 内，不能包含路径跳转、网络地址或命令。':
    'The upload directory must be within the server-approved root {root}, without path traversal, network addresses or commands.',
  '生成结果目录须位于服务端批准的本地目录范围 {root} 内，不能包含路径跳转、网络地址或命令。':
    'The results directory must be within the server-approved root {root}, without path traversal, network addresses or commands.',
  '所选组件已安装、需先检测或不支持安装，请核对组件详情；不重复安装已有组件。':
    'The selected components are installed, need a check first or cannot be installed. Review component details; existing components are not reinstalled.',
  '安装选择无效。': 'Invalid installation selection.',
  '服务器结果已读取，但无法清除本功能的恢复记录。请恢复会话存储权限并再次核对；未重放请求。':
    'The server result was read, but this feature’s recovery record could not be cleared. Restore session-storage access and check again; the request was not replayed.',
  '环境操作失败。': 'The environment operation failed.',
  '浏览器无法创建安全请求 ID，未发送环境操作。请在受信任的本地浏览器打开页面。':
    'The browser could not create a secure request ID. No environment operation was sent; open the page in a trusted local browser.',
  '服务器请求 ID 对应的操作参数不一致。保留恢复记录，不重放或认领另一项操作。':
    'The server operation parameters do not match the request ID. The recovery record is retained; no request is replayed and no other operation is adopted.',
  '服务器有另一项环境操作正在运行。请等待并再次核对，不重放安装请求。':
    'Another environment operation is running. Wait and check again; do not replay the installation request.',
  '无法核对服务器状态。': 'Could not verify the server state.',
  '无法清除本功能的恢复记录。请恢复会话存储权限；未发送请求。':
    'Could not clear this feature’s recovery record. Restore session-storage access; no request was sent.',
  安装工具: 'Installation tools',
  基础运行环境: 'Base runtime',
  结构识别: 'Structure recognition',
  'ADMET 分析': 'ADMET analysis',
  未检测: 'Unchecked',
  检测中: 'Checking',
  缺失: 'Missing',
  不完整: 'Incomplete',
  可用: 'Available',
  未配置: 'Not configured',
  版本不兼容: 'Incompatible version',
  检测失败: 'Check failed',
  受管安装工具: 'Managed installer',
  '本软件专属 uv；不依赖或修改全局工具。':
    'Application-managed uv; does not depend on or modify global tools.',
  基础提取环境: 'Base extraction runtime',
  '单一 Python 3.12 PDF、RapidOCR 和 RDKit 运行环境。':
    'One Python 3.12 runtime for PDF, RapidOCR and RDKit.',
  'DECIMER 结构环境': 'DECIMER runtime',
  'Python 3.10.20 / DECIMER 2.8.0 / Segmentation 1.5.0 / TF 2.15.1 / NumPy 1.26.4，强制 CPU。':
    'Python 3.10.20 / DECIMER 2.8.0 / Segmentation 1.5.0 / TF 2.15.1 / NumPy 1.26.4; CPU only.',
  'DECIMER 模型权重': 'DECIMER model weights',
  '专利印刷 OCSR 和分割权重；按需安装，不下载未使用的手绘模型。加载检查不是识别准确性验收。':
    'Printed-patent OCSR and segmentation weights, installed as needed. Unused hand-drawn models are not downloaded. A loading check does not validate recognition accuracy.',
  'ADMET CPU 环境': 'ADMET CPU runtime',
  '独立 Python 3.12 / ADMET-AI 2.0.1 / Chemprop 2 / CPU Torch；不是实验测量。':
    'Isolated Python 3.12 / ADMET-AI 2.0.1 / Chemprop 2 / CPU Torch; not experimental measurements.',
  'ADMET 模型权重': 'ADMET model weights',
  '十个官方 pt 模型及端点元数据；不复制或使用 DrugBank 参考集。':
    'Ten official pt models and endpoint metadata; the DrugBank reference dataset is not copied or used.',
  本地手性兜底环境: 'Local stereo-rescue runtime',
  '受限 CPU 兜底；仅在主模型丢失手性且连接图一致时使用，不并行常驻。':
    'Bounded CPU rescue, used only when the primary model loses stereo and the connectivity graph matches. No concurrent resident worker.',
  本地手性兜底模型: 'Local stereo-rescue model',
  '固定官方模型，加载检查不等于预测准确性验收。':
    'Pinned official model; loading checks do not validate prediction accuracy.',
  '安装目录必须是服务端批准的本地目录，不接受 C 盘、UNC、网络地址或命令。':
    'The installation directory must be server-approved and local. C-drive paths, UNC paths, network addresses and commands are not accepted.',
  '安装目录须位于服务端批准根目录内，不能包含路径跳转。':
    'The installation directory must be within the server-approved root, without path traversal.',
  '组件依赖目录无效或超出支持组件范围，请刷新后重新选择安装组合。':
    'The dependency catalog is invalid or exceeds the supported components. Refresh and select the installation again.',
  '组件依赖 {id} 未在服务端目录中声明，不能确认安装。':
    'Dependency {id} is absent from the server catalog. Installation cannot be confirmed.',
  '服务端组件依赖存在循环，不能确认安装。':
    'The server’s component dependencies contain a cycle. Installation cannot be confirmed.',
  '服务端组件依赖元数据缺失、重复或超出支持组件范围。':
    'Server dependency metadata is missing, duplicated or exceeds the supported components.',
  '服务端组件依赖不能包含自身。': 'A server component cannot depend on itself.',
  恢复记录无效: 'Invalid recovery record',
  恢复记录过大: 'Recovery record too large',
  未知恢复记录: 'Unknown recovery record',
  '恢复信息无法读取，未执行任何操作。请先检查配置状态，再确认清除损坏记录。':
    'Recovery information could not be read. No operation was performed. Check configuration status before confirming removal of the damaged record.',
  '无法保存环境操作的恢复信息，未发送请求。请允许本地站点的会话存储后再试。':
    'Recovery information could not be saved; no request was sent. Allow session storage for this local site before retrying.',
  '服务端未提供有效的完整部署计划，请刷新或更新匹配的后端。':
    'The server did not provide a valid complete setup plan. Refresh or update to a matching backend.',
  '服务端完整部署计划未包含正确顺序的全部前置依赖。':
    'The server’s complete setup plan does not include all prerequisites in the correct order.',
  缺少依赖: 'Missing dependencies',
  '已安装·已验证': 'Installed · Verified',
  '已存在·待复检': 'Present · Recheck required',
  '已存在·待检测': 'Present · Check required',
  '状态未知·待复检': 'Unknown · Recheck required',
  '状态未知·待检测': 'Unknown · Check required',
  '专利标识须为最多 64 个字符的 ASCII 标识，以字母开头；仅 WO 可包含 / 并自动归一化，不能输入路径或命令。':
    'Use an ASCII patent identifier of up to 64 characters, starting with a letter. Only WO identifiers may contain /, which is normalized. Paths and commands are not accepted.',
  // External LLM configuration, bounded recovery and generated safe errors.
  'LLM 局部修复': 'LLM local repair',
  剩余调用次数未知: 'Remaining calls unknown',
  '剩余调用 {calls} 次': 'Remaining calls: {calls}',
  ' · 本次重试等待 {seconds} 秒（服务端观察）':
    ' · Retry wait: {seconds} seconds (server observation)',
  ' · 重试等待时间未知': ' · Retry wait unknown',
  '配置 LLM API': 'Configure LLM API',
  '请先在环境管理中保存并启用完整的 API 配置与外发授权。':
    'Save and enable a complete API configuration and disclosure consent in Environment first.',
  '授权响应不属于当前项目。': 'The authorization response does not belong to this project.',
  '更新 API 授权': 'Renew API authorization',
  'API 授权已更新，未开始提取。核对后可手动继续提取。':
    'API authorization renewed. Extraction has not started; review the state before manually resuming.',
  刷新核对任务与配置: 'Refresh task & settings',
  '更新此任务的 API 授权？': 'Renew this task’s API authorization?',
  '只允许这个任务使用已保存且相同服务、模型和协议的凭据。不重置配额、不开始提取、不调用模型；成功后仅刷新，需手动继续提取。':
    'Authorize this task to use saved credentials for the same service, model and protocol. Quota is not reset; no extraction or model call starts. Success only refreshes the state; resume extraction manually.',
  '正在读取当前 API 配置…': 'Loading current API settings…',
  服务: 'Service',
  模型: 'Model',
  协议: 'Protocol',
  前往环境管理核对配置: 'Review settings in Environment',
  '· 已配置不代表模型验收。': '· Configuration does not validate the model.',
  '任务状态已改变，请刷新核对后再操作。':
    'The task state changed. Refresh and review before proceeding.',
  '正在更新…': 'Updating…',
  确认更新授权: 'Confirm authorization renewal',
  '正在读取…': 'Loading…',
  无法读取: 'Unavailable',
  尚未读取: 'Not loaded',
  'LLM API 状态': 'LLM API status',
  '仅外部 API，不在本机部署模型': 'External API only; no local model deployment',
  '上次请求结果尚未确认。请先读取服务器状态。':
    'The previous request’s result is unconfirmed. Read the server state first.',
  'LLM API 设置': 'LLM API settings',
  'API 协议': 'API protocol',
  'OpenAI 兼容': 'OpenAI-compatible',
  响应格式: 'Response format',
  'JSON 格式': 'JSON format',
  '严格 JSON Schema': 'Strict JSON Schema',
  'JSON 模式': 'JSON mode',
  '仅提示词 JSON': 'Prompt-only JSON',
  '配置由环境变量管理，网页只读。':
    'Settings are managed by environment variables. This page is read-only.',
  '设置变更仅影响后续新任务；续跑沿用原配置快照与剩余调用配额。':
    'Changes apply only to future tasks. Resumed tasks retain their original settings snapshot and remaining quota.',
  'LLM API 配置': 'LLM API configuration',
  'HTTPS API 基础地址': 'HTTPS API base URL',
  'API 密钥': 'API key',
  '保存时清除密钥并关闭。': 'Saving clears the key and disables the API.',
  '已保存密钥；留空保留，不回显。':
    'A key is saved. Leave blank to retain it; it is never displayed.',
  '尚未保存密钥。': 'No key saved yet.',
  清除密钥并关闭: 'Clear key & disable',
  复核模式: 'Review mode',
  '关闭（Off）': 'Disabled (Off)',
  '出错时复核（on-error）': 'Review on error (on-error)',
  '质量复核（quality）': 'Quality review (quality)',
  '关闭或撤回授权将停止外发；质量模式额外复核列映射。':
    'Disabling the API or withdrawing consent stops disclosure. Quality mode also reviews column mapping.',
  '我同意向所选外部 API 发送有限的局部文字':
    'I consent to sending bounded local text to the selected external API',
  '仅局部表头、位置和校验证据，不发送整份 PDF、分子图、SMILES 或全部数据行。':
    'Only local headers, positions and validation evidence are sent—not whole PDFs, molecular graphs, SMILES or all data rows.',
  固定调用上限: 'Fixed request limits',
  '每任务最多 {calls} 次 · 超时 {seconds} 秒 · 输入/输出 {input}/{output} 字符 · 输出 {tokens} token':
    'Up to {calls} calls per task · Timeout {seconds} seconds · Input/output {input}/{output} characters · Output {tokens} tokens',
  '正在核对服务器设置…': 'Checking server settings…',
  刷新服务器状态: 'Refresh server state',
  '服务器设置已更新，未覆盖你的非密钥输入。请核对后继续；密钥需重新输入。':
    'Server settings changed. Your non-key inputs are retained; review them before continuing and re-enter the key.',
  '设置已保存。': 'Settings saved.',
  '接口测试通过。': 'API test passed.',
  '接口测试失败。{reason}': 'API test failed. {reason}',
  '已配置不等于模型可用；接口测试只校验随机合成样本，不代表真实模型提取或科学验收。':
    'Configured does not mean the model is available. The API test checks only a random synthetic sample, not real extraction or scientific acceptance.',
  '请补全 API 配置。': 'Complete the API configuration.',
  测试接口: 'Test API',
  '请先保存设置。': 'Save settings first.',
  '处理中…': 'Processing…',
  确认接口测试: 'Confirm API test',
  '仅发送固定的合成文本，不含真实专利内容。可能产生 API 费用。':
    'Only a fixed synthetic text sample is sent, without real patent content. API charges may apply.',
  '只测试已保存配置；不自动测试或重试。':
    'Tests saved settings only; no automatic testing or retries.',
  取消测试: 'Cancel test',
  '测试中…': 'Testing…',
  确认发送测试: 'Confirm test request',
  '请输入 HTTPS API 基础地址，不得包含凭据、查询参数或片段。':
    'Enter an HTTPS API base URL without credentials, query parameters or fragments.',
  '模型名称无效。': 'Invalid model name.',
  '密钥格式无效，请重新输入。': 'Invalid key format. Re-enter the key.',
  '地址、模型或协议已改变，请输入新密钥，或明确清除密钥并关闭。':
    'The URL, model or protocol changed. Enter a new key, or explicitly clear the key and disable the API.',
  '启用前请明确同意发送有限局部文字。':
    'Explicitly consent to sending bounded local text before enabling the API.',
  '启用前请填写 API 地址、模型和密钥。':
    'Provide an API URL, model and key before enabling the API.',
  已关闭: 'Disabled',
  配置未完成: 'Configuration incomplete',
  已配置: 'Configured',
  '随机验证样本校验通过。': 'The random verification sample passed validation.',
  '接口未正确返回随机验证样本，请检查协议及 JSON 响应格式。':
    'The API did not return the random verification sample correctly. Check the protocol and JSON response format.',
  '无法完成接口请求，请检查服务地址、网络及服务状态。':
    'Could not complete the API request. Check the service URL, network and service status.',
  '测试期间配置或授权已改变，请刷新核对后再明确测试。':
    'Settings or authorization changed during testing. Refresh and review before explicitly testing again.',
  '合成测试超出输入预算，请联系维护者核对调用限制。':
    'The synthetic test exceeds the input budget. Ask the maintainer to review request limits.',
  '接口认证失败，请检查已保存密钥及其模型访问权限。':
    'API authentication failed. Check the saved key and its model access permissions.',
  '接口限流或额度不足，请核对服务商额度并稍后手动测试。':
    'The API is rate-limited or out of quota. Review the provider quota and test manually later.',
  '外部服务暂不可用，请检查服务商状态并稍后手动测试。':
    'The external service is temporarily unavailable. Check provider status and test manually later.',
  '接口请求超时，请检查网络及服务状态，核对后再手动测试。':
    'The API request timed out. Check the network and service status before testing manually again.',
  '接口测试已取消，未取得有效验证结果。':
    'The API test was cancelled; no valid verification result was obtained.',
  '私有缓存不可用，请联系维护者检查存储及权限。':
    'The private cache is unavailable. Ask the maintainer to check storage and permissions.',
  '私有缓存未通过安全检查，请联系维护者核对；不要删除缓存以绕过检查。':
    'The private cache failed security checks. Ask the maintainer to investigate; do not delete it to bypass checks.',
  '尚未配置 API 地址。': 'No API URL configured.',
  '尚未配置模型。': 'No model configured.',
  '尚未配置密钥。': 'No key configured.',
  '尚未同意发送局部文字。': 'No consent to send local text.',
  '需要明确同意发送局部文字。': 'Explicit consent to send local text is required.',
  '外部接口拒绝请求，请检查配置。': 'The external API rejected the request. Check settings.',
  '接口返回格式未通过校验，请检查协议及 JSON 响应格式。':
    'The API response format failed validation. Check the protocol and JSON response format.',
  '接口限流或额度不足，请核对服务商额度并稍后手动恢复。':
    'The API is rate-limited or out of quota. Review the provider quota and resume manually later.',
  '外部服务暂不可用，请检查服务商状态并稍后手动恢复。':
    'The external service is temporarily unavailable. Check provider status and resume manually later.',
  '接口请求超时，请检查网络及服务状态后再操作。':
    'The API request timed out. Check the network and service status before proceeding.',
  '接口请求已取消，未取得有效结果。':
    'The API request was cancelled; no valid result was obtained.',
  '无法连接接口。': 'Could not connect to the API.',
  '此任务的 API 授权已撤回，请核对设置后明确更新授权。':
    'This task’s API authorization was revoked. Review settings and explicitly renew authorization.',
  '已保存凭据已改变，请核对设置后明确更新此任务授权。':
    'Saved credentials changed. Review settings and explicitly renew this task’s authorization.',
  '此任务的调用预算已耗尽；更新授权不会重置配额。':
    'This task’s request budget is exhausted. Renewing authorization does not reset quota.',
  '接口的证据回答不合法，未采用该回答；请核对原始证据与接口响应格式。':
    'The API’s evidence response was invalid and was not used. Review the original evidence and API response format.',
  '授权控制状态不可用，请联系维护者核对；不会绕过授权继续调用。':
    'Authorization control state is unavailable. Ask the maintainer to investigate; requests will not bypass authorization.',
  '传输进程启动或清理失败，请联系维护者核对；不会自动重试。':
    'The transport process failed to start or clean up. Ask the maintainer to investigate; no automatic retry occurs.',
  '已保存的 API 配置不可用，请在环境管理中核对配置。':
    'Saved API settings are unavailable. Review them in Environment.',
  '接口重定向已被拒绝，请核对直接服务地址；不会跟随重定向。':
    'The API redirect was rejected. Review the direct service URL; redirects are not followed.',
  '接口返回 HTTP 错误，请核对服务地址、权限和服务状态。':
    'The API returned an HTTP error. Review the service URL, permissions and service status.',
  局部修复已关闭: 'Local repair disabled',
  可尝试局部修复: 'Local repair available',
  局部修复受阻: 'Local repair blocked',
  局部修复等待重试: 'Local repair waiting for retry',
  局部修复预算耗尽: 'Local repair budget exhausted',
  局部修复状态不可用: 'Local repair status unavailable',
  '授权写入结果尚未确认。请先刷新核对任务和配置，不要重复提交。':
    'The authorization write is unconfirmed. Refresh the task and settings first; do not resubmit.',
  '任务、配置或授权已改变。请先刷新核对，不会自动重试授权。':
    'The task, settings or authorization changed. Refresh and review first; authorization is not retried automatically.',
  '当前任务或 API 授权接口不可用，请刷新核对。':
    'The task or API authorization endpoint is unavailable. Refresh and review.',
  '授权未被接受。请核对任务与已保存的相同服务、模型和协议。':
    'Authorization was not accepted. Review the task and saved settings for the same service, model and protocol.',
  '会话或操作权限已失效，请重新加载页面。':
    'Your session or operation permissions expired. Reload the page.',
  '授权未能确认。请刷新核对任务和配置后再操作。':
    'Authorization could not be confirmed. Refresh and review the task and settings before proceeding.',
  '请检查配置或联系服务维护者。': 'Check settings or contact the service maintainer.',
  '请核对接口配置。': 'Review API settings.',
  '请求结果尚未确认。请先刷新服务器状态，不要重复提交。':
    'The request result is unconfirmed. Refresh the server state first; do not resubmit.',
  '服务器配置已改变。请先刷新，再确认保留的输入。':
    'Server settings changed. Refresh first, then review the retained inputs.',
  '当前后端尚未提供 LLM API 设置。': 'This backend does not provide LLM API settings.',
  '配置未被接受，请检查地址、模型、密钥和发送同意。':
    'Settings were not accepted. Check the URL, model, key and disclosure consent.',
  '操作失败，请核对服务器状态后再操作。':
    'The operation failed. Review the server state before proceeding.',
  '无法读取 LLM API 设置。': 'Could not read LLM API settings.',
  '配置无效。': 'Invalid configuration.',

  // Recoverable history actions. Record titles and raw block reasons stay verbatim.
  '恢复{kind}？': 'Restore {kind}?',
  '删除{kind}？': 'Delete {kind}?',
  '将此记录恢复到日常视图。项目在回收站时，请先恢复项目，再恢复其下的记录。':
    'Restore this record to the daily view. If its project is in Trash, restore the project before its child records.',
  '正在核对服务端状态…': 'Checking server state…',
  '提交已停止；请先刷新核对状态，再决定是否重新确认。':
    'Submission stopped. Refresh and review the state before deciding whether to confirm again.',
  '服务端当前不允许此操作。': 'The server does not currently allow this operation.',
  '记录已恢复。': 'Record restored.',
  '记录已在回收站。': 'The record is in Trash.',
  关闭: 'Close',
  刷新核对状态: 'Refresh & review state',
  确认恢复: 'Confirm restore',
  确认移入回收站: 'Confirm move to Trash',
  '恢复 {title}': 'Restore {title}',
  '删除 {title}': 'Delete {title}',
  恢复: 'Restore',
  删除: 'Delete',
  记录类型: 'Record type',
  回收站记录类型: 'Trash record type',
  刷新记录: 'Refresh records',
  '先恢复项目，再恢复该项目下的任务或文件。': 'Restore the project before its tasks or files.',
  '正在读取记录…': 'Loading records…',
  没有记录: 'No records',
  '此类型回收站为空。': 'No records of this type in Trash.',
  '暂无已保存记录。': 'No saved records yet.',
  历史记录分页: 'History pagination',
  '共 {count} 条 · 第 {page} 页': 'Records: {count} · Page {page}',
  上一页历史记录: 'Previous history page',
  上一页: 'Previous page',
  下一页历史记录: 'Next history page',
  下一页: 'Next page',
  每页历史记录数量: 'History records per page',
  '{count} 条/页': '{count} per page',
  项目: 'Project',
  已生成文件: 'Generated files',
  环境操作: 'Environment operation',
  '原文、生成文件和审计仍保留在磁盘上，不释放磁盘空间。':
    'Originals, generated files and audit records remain on disk. No disk space is reclaimed.',
  '将此项目及其 PDF、结果和历史从日常视图移入可恢复回收站。':
    'Move this project and its PDF, results and history from the daily view to recoverable Trash.',
  '只将此任务记录移入回收站。原始 PDF、当前表格、产物、生产记录和检查点文件不变。':
    'Move only this task record to Trash. The original PDF, current table, artifacts, producer records and checkpoint files are unchanged.',
  '只将此已保存文件的列表记录移入回收站，磁盘上的文件不被删除。':
    'Move only this saved file’s list record to Trash. The file is not deleted from disk.',
  '只将此终态操作记录移入回收站，不卸载环境，也不改变环境就绪状态。':
    'Move only this terminal operation record to Trash. Environments are not uninstalled and readiness is unchanged.',
  '无法核对记录状态。': 'Could not verify the record state.',
  '操作结果无法确认，请先刷新核对状态。':
    'The operation result could not be confirmed. Refresh and review the state first.',
};
