import { useState } from 'react';
import { FileUp } from 'lucide-react';
import { api } from '../../api';
import type { Project } from '../../api/types';
import { validatePdf } from '../../model/uploads';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice } from '../../components/Feedback';
import { UiError, useTranslation } from '../../i18n';

export function AttachPdfDialog({
  project,
  onClose,
  onUploaded,
}: {
  project: Project;
  onClose: () => void;
  onUploaded: (project: Project) => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  async function submit() {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      if (!file) throw new UiError('请选择原始专利 PDF。');
      await validatePdf(file);
      onUploaded(await api.attachPdf(project.id, file));
    } catch (e) {
      setError(e instanceof Error ? e : new UiError('补充原文失败。'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={t('补充项目原始 PDF')} onClose={onClose} busy={busy}>
      <form
        className="dialog-body"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p className="muted">
          {t('只补充当前项目的真实原文。服务端将核对记录的来源 SHA，不能用其他文档替换来源。')}
        </p>
        <label className="upload-drop">
          <FileUp size={30} />
          <strong>{file?.name ?? t('选择原始专利 PDF')}</strong>
          <span>{t('PDF · 最大 128 MiB · 不支持加密文档')}</span>
          <input
            data-initial-focus
            aria-label={t('原始专利 PDF 文件')}
            type="file"
            accept="application/pdf,.pdf"
            disabled={busy}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setError(null);
            }}
          />
        </label>
        {error && <ErrorNotice error={error} />}
        <footer className="dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            {t('取消')}
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? t('正在核对原文…') : t('上传并核对原始 PDF')}
          </button>
        </footer>
      </form>
    </Dialog>
  );
}
