/** Recoverable history actions. Record titles and raw block reasons stay verbatim. */
export const history: Readonly<Record<string, string>> = {
  清空回收站: 'Empty Trash',
  '回收站中的记录可恢复；清空后会永久移除记录并清理已核实未引用的文件。':
    'Trashed records can be restored. Empty Trash permanently removes records and verified unreferenced files.',
  '清空回收站？': 'Empty Trash?',
  '正在核对全部回收站…': 'Checking all trashed records…',
  '全部类型、全部分页，共 {count} 条记录。': 'All record types and pages: {count} records.',
  '全部类型、全部分页，共 1 条记录。': 'All record types and pages: 1 record.',
  '已永久移除 {count} 条记录。': 'Permanently removed {count} records.',
  '已永久移除 1 条记录。': 'Permanently removed 1 record.',
  '{count} 条记录仍有活动或未核实的进程，暂不能清空。':
    '{count} records have active or unverified processes. Trash cannot be cleared yet.',
  '清空不可撤销。只删除已核实未被引用的原始文件和产物；被引用的文件、共享环境和审计保留。':
    'Emptying Trash cannot be undone. Only verified unreferenced originals and artifacts are deleted; referenced files, shared environments and audit records remain.',
  '可清理 {count} 个未引用文件。': '{count} unreferenced files can be deleted.',
  '可清理 1 个未引用文件。': '1 unreferenced file can be deleted.',
  '{count} 组被引用、导入或无法核实的资产将保留。':
    '{count} referenced, imported or unverified asset groups will be retained.',
  '1 组被引用、导入或无法核实的资产将保留。':
    '1 referenced, imported or unverified asset group will be retained.',
  '已删除 1 个文件。': 'Deleted 1 file.',
  '已删除 {count} 个文件。': 'Deleted {count} files.',
  '新增引用的 1 个文件已保留。': '1 newly referenced file was retained.',
  '新增引用的 {count} 个文件已保留。': '{count} newly referenced files were retained.',
  '文件清理未完成，可继续原操作。': 'File cleanup is incomplete. Continue the saved operation.',
  继续清理文件: 'Continue file cleanup',
  '清空结果尚未确认。请先核对，不会自动重复删除。':
    'The clear result is unconfirmed. Check its state first; deletion is never automatically repeated.',
  核对回收站: 'Check Trash',
  重试此清空操作: 'Retry this clear request',
  确认清空全部: 'Confirm empty all',
  '清空结果尚未确认。': 'The clear result is unconfirmed.',
  '清空回执不匹配，未重复提交。': 'The clear receipt does not match. No submission was repeated.',
  '回收站已变化。请关闭后重新核对；未重复清空。':
    'Trash has changed. Close and review it again; no clear request was repeated.',
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
