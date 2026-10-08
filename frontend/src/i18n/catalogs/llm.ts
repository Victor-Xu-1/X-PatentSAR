/** External LLM configuration, bounded recovery and generated safe errors. */
export const llm: Readonly<Record<string, string>> = {
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
};
