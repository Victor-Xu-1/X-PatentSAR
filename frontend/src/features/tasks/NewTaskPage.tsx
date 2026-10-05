import { useEffect, useRef, useState } from 'react';
import { FileUp } from 'lucide-react';
import type { Project } from '../../api/types';
import { ErrorNotice } from '../../components/Feedback';
import { defaultJobOptions } from '../../model/tasks';
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
  const task = useTaskSubmission(onCreated);
  const initial = useRef<HTMLInputElement>(null);
  useEffect(() => initial.current?.focus(), []);
  const busy = task.busy !== null;
  const inputLocked = busy || Boolean(task.created) || task.uncertain;
  return (
    <section className="new-task-page">
      <header className="task-heading">
        <h1>上传专利 PDF</h1>
      </header>
      <form
        className="task-form"
        aria-busy={busy}
        onSubmit={(event) => {
          event.preventDefault();
          if (!connected || !ready) return;
          void task.submit({ file, title: '', patentId: '', options: defaultJobOptions });
        }}
      >
        <fieldset className="task-inputs" disabled={inputLocked}>
          <legend className="sr-only">专利 PDF</legend>
          <label className="upload-drop">
            <span className="upload-icon" aria-hidden="true">
              <FileUp size={30} />
            </span>
            <strong>{file?.name ?? '选择专利 PDF'}</strong>
            <span>PDF · 最大 128 MiB</span>
            <input
              ref={initial}
              aria-label="原始专利 PDF 文件"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
        </fieldset>
        <div className="task-status" aria-live="polite">
          {task.created && (
            <p className="success-banner">
              PDF 已保存：{task.created.title}（{task.created.pdf.page_count} 页）。
            </p>
          )}
          {task.error && <ErrorNotice error={task.error} />}
          {connected && !ready && (
            <p className="info-banner">
              提取或 ADMET 环境尚未就绪，请到<a href="#/settings">环境管理</a>检测。
            </p>
          )}
          {task.uncertain && !task.created && (
            <p className="info-banner">
              上传结果未知，请先在<a href="#/projects">最近文件</a>核实，不要重复上传。
            </p>
          )}
        </div>
        <footer className="task-submit">
          {task.created && (
            <button type="button" disabled={busy} onClick={() => onOpen(task.created!.id)}>
              打开已保存文件
            </button>
          )}
          {task.uncertain ? (
            task.created && (
              <button type="button" disabled={busy} onClick={() => void task.check()}>
                检查任务状态
              </button>
            )
          ) : (
            <button
              type="submit"
              className="primary"
              disabled={!connected || busy || !ready || (!file && !task.created)}
            >
              {task.busy === 'upload'
                ? '正在上传…'
                : task.busy === 'start'
                  ? '正在启动…'
                  : task.created
                    ? '重试启动'
                    : '开始提取'}
            </button>
          )}
        </footer>
      </form>
    </section>
  );
}
