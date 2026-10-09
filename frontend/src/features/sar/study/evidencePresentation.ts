/** Human interface summaries; raw machine evidence remains available unchanged. */
export const evidenceCopy: Record<string, string> = {
  source_structure_ineligible: '结构尚未核定，保留记录但不参加比较',
  stereochemistry_unassigned: '手性未确定，暂不参与候选排序',
  priority_requires_complete_recorded_context: '实验条件不完整，暂不参与候选排序',
  conflicting_measurements: '重复测量冲突，不能确定强弱',
  partial_missing_measurements: '部分重复测量缺失',
  graph_alias_measurements_conflict: '同结构的原始编号记录存在冲突',
  nonindependent_source_graph: '相同结构不作为独立候选重复入选',
  logs_not_provided: '未提供 LogS，保持未知',
  descriptor_out_of_domain: '结构超出性质计算适用范围',
  imported_predictions_unverified: '导入的预测尚未验证',
  operator_declared_context_not_automatic_verification: '实验条件来自本研究的原文人工核对',
  activity_absence_retained_in_report: '没有活性的结构仍完整保留',
  activity_unresolved_retained_in_report: '不确定读数单独保留，不强行排序',
  fewer_than_five_independent_rankable_graphs: '可独立排序的候选不足五个，不补造结果',
  confirmed_core_groups_overlap: '已确认母核组存在交集，不能相加作独立样本',
  confirmed_core_membership_unresolved: '部分母核归属有歧义，未强行分组',
  scaffold_unavailable_rows_retained: '尚未核定的结构仍保留在完整数据表中',
};
export const originCopy: Record<string, string> = {
  computed_rdkit: '结构计算值',
  imported: '导入值',
  manual: '人工修订值',
  manual_null: '人工保留空值',
  not_provided: '未提供',
};
export function evidenceSummaries(codes: string[]) {
  return [...new Set(codes.flatMap((code) => (evidenceCopy[code] ? [evidenceCopy[code]] : [])))];
}
