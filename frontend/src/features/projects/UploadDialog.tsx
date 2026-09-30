import { useState } from 'react';
import { FileUp } from 'lucide-react';
import { api } from '../../api';
import type { Project } from '../../api/types';
import { validatePdf } from '../../model/uploads';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice } from '../../components/Feedback';

export function UploadDialog({
  project,
  onClose,
  onUploaded,
}: {
  project: Project | null;
  onClose: () => void;
  onUploaded: (project: Project) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  async function submit() {
    setError(null);
    if (!file) {
      setError(new Error('请选择原始专利 PDF。'));
      return;
    }
    if (!project && !title.trim()) {
      setError(new Error('请输入项目名称。'));
      return;
    }
    setBusy(true);
    try {
      await validatePdf(file);
      const uploaded = project
        ? await api.attachPdf(project.id, file)
        : await api.upload(file, title.trim());
      onUploaded(uploaded);
    } catch (e) {
      setError(e instanceof Error ? e : new Error('上传失败。'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={project ? '补充历史项目原始 PDF' : '新建专利项目'} onClose={onClose} busy={busy}>
      <form
        className="dialog-body"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p className="muted">
          {project
            ? '服务端将核对历史来源 SHA。只上传对应的原始 PDF，不能以其他文档替换来源。'
            : '上传原始专利文档。项目建立后可启动确定性提取流水线，不会自动调用付费模型。'}
        </p>
        {!project && (
          <label className="form-field">
            项目名称
            <input
              data-initial-focus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
              disabled={busy}
              required
              placeholder="为此专利项目命名"
            />
          </label>
        )}
        <label className="upload-drop">
          <FileUp size={30} />
          <strong>{file?.name ?? '选择原始专利 PDF'}</strong>
          <span>PDF · 最大 128 MiB · 不支持加密文档</span>
          <input
            type="file"
            aria-label="原始专利 PDF 文件"
            accept="application/pdf,.pdf"
            disabled={busy}
            onChange={(e) => {
              const next = e.target.files?.[0] ?? null;
              setFile(next);
              setError(null);
              if (next && !title) setTitle(next.name.replace(/\.pdf$/i, ''));
            }}
          />
        </label>
        {file && (
          <p className="muted">
            {(file.size / 1024 / 1024).toFixed(2)} MiB · 完整性由服务端真实 PDF 解析器验证
          </p>
        )}
        {error && <ErrorNotice error={error} />}
        <footer className="dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? '正在上传，请勿重复提交…' : project ? '上传并核对原始 PDF' : '上传并创建项目'}
          </button>
        </footer>
      </form>
    </Dialog>
  );
}
