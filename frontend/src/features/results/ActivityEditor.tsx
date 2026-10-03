import { Plus, Trash2 } from 'lucide-react';
import type { ActivityDraft } from './correctionDraft';

export function ActivityEditor({
  values,
  disabled,
  onChange,
}: {
  values: ActivityDraft[];
  disabled: boolean;
  onChange: (values: ActivityDraft[]) => void;
}) {
  function patch(index: number, update: Partial<ActivityDraft>) {
    onChange(values.map((value, i) => (i === index ? { ...value, ...update } : value)));
  }
  return (
    <section className="activity-editor" aria-label="编辑活性数据">
      <header>
        <h3>活性数据</h3>
        <button
          type="button"
          disabled={disabled || values.length >= 100}
          onClick={() =>
            onChange([
              ...values,
              { name: '', value: '', valueKind: 'text', unit: '', target: '', assay: '', page: '' },
            ])
          }
        >
          <Plus size={14} />
          添加
        </button>
      </header>
      {values.map((value, index) => (
        <fieldset key={index} disabled={disabled} className="activity-edit-row">
          <legend>测量 {index + 1}</legend>
          <label>
            指标
            <input
              aria-label={`测量 ${index + 1} 指标`}
              value={value.name}
              maxLength={300}
              required
              onChange={(e) => patch(index, { name: e.target.value })}
            />
          </label>
          <label>
            值
            <input
              aria-label={`测量 ${index + 1} 值`}
              value={value.value}
              maxLength={1000}
              onChange={(e) => patch(index, { value: e.target.value })}
            />
          </label>
          <label>
            类型
            <select
              aria-label={`测量 ${index + 1} 值类型`}
              value={value.valueKind}
              onChange={(e) =>
                patch(index, { valueKind: e.target.value === 'number' ? 'number' : 'text' })
              }
            >
              <option value="text">文本 / 等级</option>
              <option value="number">数值</option>
            </select>
          </label>
          <label>
            单位
            <input
              aria-label={`测量 ${index + 1} 单位`}
              value={value.unit}
              maxLength={100}
              onChange={(e) => patch(index, { unit: e.target.value })}
            />
          </label>
          <label>
            靶点
            <input
              aria-label={`测量 ${index + 1} 靶点`}
              value={value.target}
              maxLength={300}
              onChange={(e) => patch(index, { target: e.target.value })}
            />
          </label>
          <label>
            原文页
            <input
              aria-label={`测量 ${index + 1} 原文页`}
              inputMode="numeric"
              value={value.page}
              onChange={(e) => patch(index, { page: e.target.value })}
            />
          </label>
          <label className="activity-edit-assay">
            实验
            <input
              aria-label={`测量 ${index + 1} 实验`}
              value={value.assay}
              maxLength={1000}
              onChange={(e) => patch(index, { assay: e.target.value })}
            />
          </label>
          <button
            type="button"
            aria-label={`删除测量 ${index + 1}`}
            onClick={() => onChange(values.filter((_, i) => i !== index))}
          >
            <Trash2 size={14} />
          </button>
        </fieldset>
      ))}
      {!values.length && <p className="muted">暂无活性数据</p>}
    </section>
  );
}
