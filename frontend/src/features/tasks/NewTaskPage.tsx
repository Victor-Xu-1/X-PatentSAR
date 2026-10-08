import { useEffect, useRef, useState } from 'react';
import { ArrowRight, FileText, FileUp } from 'lucide-react';
import type { Project } from '../../api/types';
import { ErrorNotice } from '../../components/Feedback';
import { defaultJobOptions } from '../../model/tasks';
import { useTaskSubmission } from './useTaskSubmission';
import { useTranslation } from '../../i18n';

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
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const task = useTaskSubmission(onCreated);
  const initial = useRef<HTMLInputElement>(null);
  useEffect(() => initial.current?.focus(), []);
  const busy = task.busy !== null;
  const inputLocked = busy || Boolean(task.created) || task.uncertain;
  return (
    <section className="new-task-page" aria-labelledby="new-task-heading">
      <header className="task-heading">
        <h1 id="new-task-heading">{t('上传专利 PDF')}</h1>
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
          <legend className="sr-only">{t('专利 PDF')}</legend>
          <label className={`upload-drop${file ? ' has-file' : ''}`}>
            <span className="upload-icon" aria-hidden="true">
              {file ? <FileText size={28} /> : <FileUp size={28} />}
            </span>
            <strong className="upload-file-name" aria-live="polite">
              {file?.name ?? t('选择专利 PDF')}
            </strong>
            <span id="pdf-upload-limit">{t('PDF · 最大 128 MiB')}</span>
            <input
              ref={initial}
              aria-label={t('原始专利 PDF 文件')}
              aria-describedby="pdf-upload-limit"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
        </fieldset>
        <div className="task-status" aria-live="polite">
          {task.created && (
            <p className="success-banner">
              {t('PDF 已保存：{title}（{pages} 页）。', {
                title: task.created.title,
                pages: task.created.pdf.page_count,
              })}
            </p>
          )}
          {task.error && <ErrorNotice error={task.error} />}
          {connected && !ready && (
            <p className="info-banner">
              {t('提取或 ADMET 环境尚未就绪，请到')}
              <a href="#/settings">{t('环境管理')}</a>
              {t('检测。')}
            </p>
          )}
          {task.uncertain && !task.created && (
            <p className="info-banner">
              {t('上传结果未知，请先在')}
              <a href="#/projects">{t('最近文件')}</a>
              {t('核实，不要重复上传。')}
            </p>
          )}
        </div>
        <footer className="task-submit">
          {task.created && (
            <button type="button" disabled={busy} onClick={() => onOpen(task.created!.id)}>
              {t('打开已保存文件')}
            </button>
          )}
          {task.uncertain ? (
            task.created && (
              <button type="button" disabled={busy} onClick={() => void task.check()}>
                {t('检查任务状态')}
              </button>
            )
          ) : (
            <button
              type="submit"
              className="primary"
              disabled={!connected || busy || !ready || (!file && !task.created)}
            >
              {task.busy === 'upload'
                ? t('正在上传…')
                : task.busy === 'start'
                  ? t('正在启动…')
                  : task.created
                    ? t('重试启动')
                    : t('开始提取')}
              {!busy && <ArrowRight size={16} aria-hidden="true" />}
            </button>
          )}
        </footer>
      </form>
    </section>
  );
}
