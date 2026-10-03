import { useState } from 'react';
import { Download } from 'lucide-react';
import { api } from '../../api';
import type { Filters, Project } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice } from '../../components/Feedback';
import { saveBlob } from '../../model/uploads';

export function ExportDialog({
  project,
  selected,
  filters,
  onClose,
}: {
  project: Project;
  selected: string[];
  filters: Filters;
  onClose: () => void;
}) {
  const [format, setFormat] = useState<'csv' | 'json'>('csv');
  const filtered = Boolean(filters.q || filters.target || filters.confidence || filters.review);
  const [scope, setScope] = useState<'selected' | 'filtered' | 'all'>(
    selected.length ? 'selected' : filtered ? 'filtered' : 'all',
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  async function submit() {
    setBusy(true);
    setError(null);
    setDownloaded(false);
    try {
      const blob =
        scope === 'filtered'
          ? await api.export(project.id, format, [], filters)
          : await api.export(project.id, format, scope === 'selected' ? selected : []);
      saveBlob(blob, `X-PatentSAR-${project.id.replace(/[^a-zA-Z0-9_-]/g, '_')}.${format}`);
      setDownloaded(true);
    } catch (e) {
      setError(e instanceof Error ? e : new Error('导出失败。'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title="导出结构与活性结果" onClose={onClose} busy={busy}>
      <form
        className="dialog-body"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="info-banner">
          {project.acceptance.state === 'accepted'
            ? '原始提取核心 QA 已通过。人工修正与计算指标单独记录，含这些内容的导出仅供复核 / 研究。'
            : '当前项目未通过当前核心 QA，下载仅为复核材料，不代表正式交付验收通过。'}
        </div>
        <label className="form-field">
          导出范围
          <select
            data-initial-focus
            value={scope}
            onChange={(e) => setScope(e.target.value as 'selected' | 'filtered' | 'all')}
            disabled={busy}
          >
            <option value="selected" disabled={!selected.length}>
              已选择 {selected.length} 个化合物
            </option>
            <option value="filtered">当前筛选结果（全部匹配页，不限当前页）</option>
            <option value="all">全部结果（不受当前表格筛选限制）</option>
          </select>
        </label>
        {scope === 'filtered' && (
          <p className="muted">
            关键词：{filters.q || '全部'} · 靶点：{filters.target || '全部'} · 置信度：
            {filters.confidence || '全部'} · 复核：{filters.review || '全部'}
            。指标显示选择仅改变行内显示，不属于导出查询筛选。
          </p>
        )}
        <label className="form-field">
          文件格式
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as 'csv' | 'json')}
            disabled={busy}
          >
            <option value="csv">CSV · 适合表格分析</option>
            <option value="json">JSON · 保留结构化数据</option>
          </select>
        </label>
        {error && <ErrorNotice error={error} />}
        {downloaded && (
          <output className="success-banner">文件已从服务端生成并交给浏览器下载。</output>
        )}
        <footer className="dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            关闭
          </button>
          <button
            type="submit"
            className="primary"
            disabled={busy || (scope === 'selected' && !selected.length)}
          >
            <Download size={16} />
            {busy ? '正在导出…' : '生成并下载'}
          </button>
        </footer>
      </form>
    </Dialog>
  );
}
