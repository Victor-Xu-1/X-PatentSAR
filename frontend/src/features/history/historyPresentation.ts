import type { HistoryKind } from '../../api/historyTypes';

export const historyLabels: Record<HistoryKind, string> = {
  project: '项目',
  job: '任务记录',
  export: '已生成文件',
  environment_operation: '环境操作',
};
export const retentionNotice = '原文、生成文件和审计仍保留在磁盘上，不释放磁盘空间。';
export const deletionScope: Record<HistoryKind, string> = {
  project: '将此项目及其 PDF、结果和历史从日常视图移入可恢复回收站。',
  job: '只将此任务记录移入回收站。原始 PDF、当前表格、产物、生产记录和检查点文件不变。',
  export: '只将此已保存文件的列表记录移入回收站，磁盘上的文件不被删除。',
  environment_operation: '只将此终态操作记录移入回收站，不卸载环境，也不改变环境就绪状态。',
};
