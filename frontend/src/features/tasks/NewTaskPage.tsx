import { useEffect, useRef, useState } from 'react';
import { FileUp } from 'lucide-react';
import type { Project } from '../../api/types';
import { ErrorNotice } from '../../components/Feedback';
import { JobOptionsFields, defaultJobOptions } from './JobOptionsFields';
import { useTaskSubmission } from './useTaskSubmission';

export function NewTaskPage({
  ready,
  connected,
  onCreated,
  onOpen,
}: {
  ready: boolean;
  connected: boolean;
  onCreated: (project: Project) => void;
  onOpen: (id: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [patentId, setPatentId] = useState('');
  const [extract, setExtract] = useState(true);
  const [options, setOptions] = useState(defaultJobOptions);
  const task = useTaskSubmission(onCreated);
  const initial = useRef<HTMLInputElement>(null);
  useEffect(() => initial.current?.focus(), []);
  const busy = task.busy !== null;
  return (
    <section className="panel management-page new-task-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">NEW EXTRACTION TASK</span>
          <h1>新建提取任务</h1>
          <p className="muted">
            上传原始 PDF，建立项目后启动同一条确定性提取主链。默认严格 QA，不自动调用付费模型。
          </p>
        </div>
      </header>
      <form
        className="task-form"
        aria-busy={busy}
        onSubmit={(e) => {
          e.preventDefault();
          void task.submit({ file, title, patentId, extract, options });
        }}
      >
        <fieldset
          className="task-inputs"
          disabled={busy || Boolean(task.created) || task.uncertain}
        >
          <legend>1 · 原始专利与项目信息</legend>
          <label className="form-field">
            项目名称
            <input
              ref={initial}
              value={title}
              maxLength={200}
              required
              placeholder="为此专利项目命名"
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="form-field">
            专利标识（可选）
            <input
              value={patentId}
              maxLength={64}
              placeholder="例如 WO2026/156070；留空按文件名推断"
              onChange={(e) => setPatentId(e.target.value)}
            />
          </label>
          <label className="upload-drop">
            <FileUp size={28} />
            <strong>{file?.name ?? '选择原始专利 PDF'}</strong>
            <span>PDF · 最大 128 MiB · 服务端真实解析与校验</span>
            <input
              aria-label="原始专利 PDF 文件"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
        </fieldset>
        <div className="task-config">
          <fieldset
            className="task-mode"
            disabled={busy || Boolean(task.created) || task.uncertain}
          >
            <legend>2 · 执行方式</legend>
            <label className="option-check">
              <input
                type="radio"
                name="task-mode"
                checked={extract}
                onChange={() => setExtract(true)}
              />
              完整提取（默认）
            </label>
            <p className="muted">
              先保存原始 PDF 与项目，再创建持久化作业。若启动失败，已建项目保留，可检查或重试。
            </p>
            <label className="option-check">
              <input
                type="radio"
                name="task-mode"
                checked={!extract}
                onChange={() => setExtract(false)}
              />
              仅建立项目（不启动提取）
            </label>
          </fieldset>
          <JobOptionsFields
            options={options}
            onChange={setOptions}
            disabled={!extract || busy || task.uncertain}
          />
          {!extract && (
            <p className="info-banner">
              仅建立项目不保存作业选项；任务说明不会保存到项目。需要提取时再创建作业。
            </p>
          )}
        </div>
        <div className="task-status" aria-live="polite">
          {task.created && (
            <p className="success-banner">
              项目已建立：{task.created.title}（{task.created.pdf.page_count} 页）。原始 PDF
              已保存，不会重复上传。
            </p>
          )}
          {task.error && <ErrorNotice error={task.error} />}
          {!ready && extract && (
            <p className="info-banner">
              提取环境尚未就绪。查看<a href="#/settings">运行环境</a>
              ，或明确选择“仅建立项目”；不会自动降级执行。
            </p>
          )}
          {task.uncertain && !task.created && (
            <p className="info-banner">
              上传结果未知，请先在<a href="#/projects">项目列表</a>核实。禁止盲目重复创建。
            </p>
          )}
        </div>
        <footer className="task-submit">
          {task.created && (
            <button type="button" disabled={busy} onClick={() => onOpen(task.created!.id)}>
              打开已建立项目
            </button>
          )}
          {task.uncertain ? (
            task.created && (
              <button type="button" disabled={busy} onClick={() => void task.check()}>
                检查已建立项目的任务状态
              </button>
            )
          ) : (
            <button
              type="submit"
              className="primary"
              disabled={!connected || busy || (extract && !ready)}
            >
              {task.busy === 'upload'
                ? '正在上传并验证 PDF…'
                : task.busy === 'start'
                  ? '正在创建提取作业…'
                  : task.created
                    ? '重试启动提取'
                    : extract
                      ? '创建项目并启动完整提取'
                      : '仅上传并建立项目'}
            </button>
          )}
        </footer>
      </form>
    </section>
  );
}
