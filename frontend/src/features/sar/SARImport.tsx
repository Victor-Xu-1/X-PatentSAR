import { useCallback, useState } from 'react';
import { api } from '../../api';
import { sarApi } from '../../api/sarApi';
import type { CSVPreview, Dataset, ProjectSnapshot } from '../../api/sarTypes';
import { useSARResource } from './useSARResource';
import { Empty, Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { UiError, useTranslation } from '../../i18n';
import { CSVMappingForm } from './CSVMappingForm';
import { MutationNotice } from './MutationNotice';
import { newRequestId } from './presentation';
import { useSARMutation } from './useSARMutation';
import { TableScroll } from './TableScroll';

export function SARImport({
  active,
  sourceProjectId,
  onCreated,
  scope = '',
}: {
  active: boolean;
  sourceProjectId: string | null;
  onCreated: (dataset: Dataset) => void;
  scope?: string;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'project' | 'csv'>('project');
  const [selection, setSelection] = useState({
    source: sourceProjectId,
    value: sourceProjectId ?? '',
  });
  const projectId =
    selection.source === sourceProjectId ? selection.value : (sourceProjectId ?? '');
  const [title, setTitle] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CSVPreview | null>(null);
  const mutation = useSARMutation({ active, scope: JSON.stringify([scope, sourceProjectId]) });
  const loadProjects = useCallback((signal: AbortSignal) => api.projects(signal), []);
  const projects = useSARResource(
    'sar:source-projects',
    active && mode === 'project',
    loadProjects,
  );
  const selectedExists = projects.data?.items.some((p) => p.id === projectId);
  function snapshot() {
    if (!active || !projects.validated || !projectId || mutation.locked) return;
    const payload: ProjectSnapshot = {
      project_id: projectId,
      title: title.trim() || null,
      request_id: newRequestId(),
    };
    void mutation.run(() => sarApi.createProject(payload), onCreated, payload.request_id);
  }
  function upload() {
    if (!active || mutation.locked) return;
    void mutation.run(async () => {
      if (!file || !/\.csv$/i.test(file.name) || !file.size)
        throw new UiError('请选择非空 CSV 文件。');
      if (file.size > 8 * 1024 * 1024) throw new UiError('CSV 最大为 8 MiB。');
      if (file.name.length > 200) throw new UiError('CSV 文件名最多 200 个字符。');
      return sarApi.preview(file);
    }, setPreview);
  }
  return (
    <section className="sar-panel" aria-label={t('导入数据')}>
      <h2>{t('导入数据')}</h2>
      <div className="sar-actions">
        <button
          type="button"
          aria-pressed={mode === 'project'}
          disabled={!active || mutation.locked}
          onClick={() => setMode('project')}
        >
          {t('已提取项目快照')}
        </button>
        <button
          type="button"
          aria-pressed={mode === 'csv'}
          disabled={!active || mutation.locked}
          onClick={() => setMode('csv')}
        >
          {t('CSV 文件')}
        </button>
      </div>
      <MutationNotice
        mutation={mutation}
        disabled={!active || (mode === 'project' && !projects.validated)}
      />
      {mode === 'project' ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            snapshot();
          }}
        >
          {projects.loading && <Loading />}
          {projects.error && <SARFailure error={projects.error} onRetry={projects.reload} />}
          {projects.data?.items.length === 0 && (
            <Empty
              title="还没有文件"
              description="选择已提取项目快照或导入 CSV。打开页面不会创建数据集或启动分析。"
            />
          )}
          <fieldset disabled={!active || !projects.validated || mutation.locked}>
            <div className="sar-form-grid">
              <label>
                {t('来源项目')}
                <select
                  value={projectId}
                  onChange={(e) => setSelection({ source: sourceProjectId, value: e.target.value })}
                >
                  <option value="">{t('请选择已提取项目')}</option>
                  {projectId && !selectedExists && <option value={projectId}>{projectId}</option>}
                  {projects.data?.items.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t('数据集名称')}
                <input maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
            </div>
            <p className="sar-hint">{t('快照保留当前有效来源与修订；不会触发原始提取任务。')}</p>
            <button
              className="primary"
              type="submit"
              disabled={!projectId || Boolean(projects.error)}
            >
              {t('创建独立快照')}
            </button>
          </fieldset>
        </form>
      ) : (
        <div>
          {!preview && (
            <div className="sar-form-grid">
              <label>
                {t('选择 CSV 文件')}
                <input
                  type="file"
                  accept=".csv,text/csv"
                  disabled={!active || mutation.locked}
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <button type="button" disabled={!active || !file || mutation.locked} onClick={upload}>
                {t('服务器预览')}
              </button>
            </div>
          )}
          {!preview && <p className="sar-hint">{t('CSV · 最大 8 MiB · 最多 256 列')}</p>}
          {preview && (
            <>
              <h3>
                {t('CSV 预览')} · {preview.filename}
              </h3>
              <p>{t('CSV 原始记录数：{count}', { count: preview.row_count })}</p>
              <TableScroll label={t('CSV 预览')}>
                <table>
                  <thead>
                    <tr>
                      {preview.headers.map((header) => (
                        <th key={header}>{header}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.samples.map((row, i) => (
                      <tr key={i}>
                        {preview.headers.map((header) => (
                          <td key={header}>{row[header] ?? ''}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
              <CSVMappingForm
                key={preview.token}
                preview={preview}
                disabled={!active || mutation.locked}
                onSubmit={(payload) => {
                  void mutation.run(
                    () => sarApi.createCSV(payload),
                    (dataset) => {
                      setPreview(null);
                      setFile(null);
                      onCreated(dataset);
                    },
                    payload.request_id,
                  );
                }}
              />
              <button
                type="button"
                disabled={!active || mutation.locked}
                onClick={() => {
                  void mutation.run(
                    () => sarApi.discardPreview(preview.token),
                    () => {
                      setPreview(null);
                      setFile(null);
                    },
                  );
                }}
              >
                {t('丢弃 CSV 暂存')}
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
