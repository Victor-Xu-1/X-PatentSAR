/** Environment overview, details, storage and explicit consent. */
export const environment: Readonly<Record<string, string>> = {
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
  组件详情: 'Component details',
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
  '需要检测 · {count} 个组件': 'Check required · {count} components',
  ' · {count} 待检测': ' · {count} awaiting check',
};
