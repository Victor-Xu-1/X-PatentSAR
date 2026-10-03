import type { JobOptions } from '../../api/types';

type EditableJobOptions = Pick<
  Required<JobOptions>,
  'include_intermediates' | 'force' | 'task_note'
>;

export const defaultJobOptions: EditableJobOptions = {
  include_intermediates: false,
  force: false,
  task_note: '',
};

export function JobOptionsFields({
  options,
  onChange,
  disabled,
}: {
  options: EditableJobOptions;
  onChange: (options: EditableJobOptions) => void;
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
      <label className="form-field">
        任务说明
        <textarea
          rows={3}
          maxLength={2000}
          value={options.task_note}
          aria-describedby="task-note-help"
          onChange={(e) => onChange({ ...options, task_note: e.target.value })}
        />
      </label>
      <small id="task-note-help" className="muted">
        {options.task_note.length}/2000 · 仅作任务记录。
      </small>
    </fieldset>
  );
}
