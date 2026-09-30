import type { JobOptions } from '../../api/types';

export const defaultJobOptions = { include_intermediates: false, force: false, task_note: '' };

export function JobOptionsFields({
  options,
  onChange,
  disabled,
}: {
  options: Required<JobOptions>;
  onChange: (options: Required<JobOptions>) => void;
  disabled: boolean;
}) {
  return (
    <fieldset className="task-options" disabled={disabled}>
      <legend>提取作业选项</legend>
      <label className="option-check">
        <input
          type="checkbox"
          checked={options.include_intermediates}
          onChange={(e) => onChange({ ...options, include_intermediates: e.target.checked })}
        />
        包含中间体
      </label>
      <label className="option-check">
        <input
          type="checkbox"
          checked={options.force}
          onChange={(e) => onChange({ ...options, force: e.target.checked })}
        />
        强制重算
      </label>
      <p className="muted">
        强制重算会重新计算现有阶段；恢复任务由服务端关闭该选项以保护 checkpoint。
      </p>
      <label className="form-field">
        任务说明（运营记录）
        <textarea
          rows={3}
          maxLength={2000}
          value={options.task_note}
          aria-describedby="task-note-help"
          onChange={(e) => onChange({ ...options, task_note: e.target.value })}
        />
      </label>
      <small id="task-note-help" className="muted">
        {options.task_note.length}/2000 · 随提取任务持久化，仅作运营记录，不由 LLM 执行。
      </small>
    </fieldset>
  );
}
