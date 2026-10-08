/** Recoverable history actions. Record titles and raw block reasons stay verbatim. */
export const history: Readonly<Record<string, string>> = {
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
