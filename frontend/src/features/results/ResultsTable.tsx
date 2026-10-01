import { useEffect, useRef } from 'react';
import { FileText, MapPin, MessageSquareText } from 'lucide-react';
import type { Compound } from '../../api/types';
import { activityText, confidenceLabels, reviewLabels } from '../../model/presentation';
import { AssetImage } from '../../components/AssetImage';
import { cropPlaceholder } from '../../model/extraction';

export function ResultsTable({
  rows,
  offset,
  metric,
  selected,
  focusedId,
  onSelect,
  onSelectPage,
  onJump,
  onCrop,
  onReview,
}: {
  rows: Compound[];
  offset: number;
  metric: string;
  selected: Set<string>;
  focusedId: string | null;
  onSelect: (id: string) => void;
  onSelectPage: (checked: boolean) => void;
  onJump: (compound: Compound) => void;
  onCrop: (compound: Compound) => void;
  onReview: (compound: Compound) => void;
}) {
  const selectAll = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const all = rows.length > 0 && rows.every((row) => selected.has(row.id));
  const some = rows.some((row) => selected.has(row.id));
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = some && !all;
  }, [some, all]);
  useEffect(() => {
    if (!focusedId) return;
    const element = Array.from(
      container.current?.querySelectorAll<HTMLElement>('[data-compound]') ?? [],
    ).find((row) => row.dataset.compound === focusedId);
    element?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [focusedId, rows]);
  return (
    <div className="table-scroll" ref={container}>
      <table className="results-table">
        <caption className="sr-only">来自当前项目 API 的化合物、真实活性、来源与复核记录</caption>
        <thead>
          <tr>
            <th className="check-col">
              <input
                ref={selectAll}
                type="checkbox"
                aria-label="选择当前页全部化合物"
                checked={all}
                onChange={(e) => onSelectPage(e.target.checked)}
                disabled={!rows.length}
              />
            </th>
            <th>#</th>
            <th>结构 / 编号</th>
            <th>活性数据</th>
            <th>靶点 / 实验</th>
            <th>可信度</th>
            <th>来源位置</th>
            <th>复核</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const activities = row.activities.filter(
              (activity) => !metric || activity.name === metric,
            );
            return (
              <tr
                key={row.id}
                data-compound={row.id}
                className={focusedId === row.id ? 'source-focused' : ''}
              >
                <td>
                  <input
                    type="checkbox"
                    aria-label={`选择化合物 ${row.display_id}`}
                    checked={selected.has(row.id)}
                    onChange={() => onSelect(row.id)}
                  />
                </td>
                <td className="row-number">{offset + index + 1}</td>
                <td>
                  <div className="structure-cell">
                    <button
                      type="button"
                      className="crop-button"
                      data-focus-key={`crop:${row.id}`}
                      aria-label={`放大 ${row.display_id} 结构裁图`}
                      disabled={!row.structure_image_url}
                      onClick={() => onCrop(row)}
                    >
                      <AssetImage
                        url={row.structure_image_url}
                        alt={`${row.display_id} 结构裁图`}
                        unavailableLabel={cropPlaceholder(row)}
                      />
                    </button>
                    <strong title={row.id}>{row.display_id}</strong>
                  </div>
                </td>
                <td>
                  <div className="activity-list">
                    {activities.length ? (
                      activities.map((activity, i) => (
                        <span className="activity-value" key={i}>
                          {activityText(activity)}
                        </span>
                      ))
                    ) : (
                      <span className="muted">{metric ? '该指标无数据' : '无活性数据'}</span>
                    )}
                  </div>
                </td>
                <td>
                  <div className="assay-list">
                    {activities.length ? (
                      activities.map((activity, i) => (
                        <div key={i}>
                          <strong>{activity.target ?? '靶点未提供'}</strong>
                          <span>{activity.assay ?? '实验未提供'}</span>
                          {activity.page !== null && <small>活性来源第 {activity.page} 页</small>}
                        </div>
                      ))
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </div>
                </td>
                <td>
                  <span
                    className={`badge ${row.confidence.level}`}
                    title={row.confidence.reason ?? '置信度依据未提供'}
                  >
                    {confidenceLabels[row.confidence.level]}
                  </span>
                  <small className="confidence-score">
                    {row.confidence.score === null ? '无数值分数' : String(row.confidence.score)}
                  </small>
                </td>
                <td>
                  <div className="source-cell">
                    <FileText size={15} />
                    <div>
                      <span>
                        {row.source.page === null ? '页码未知' : `第 ${row.source.page} 页`}
                      </span>
                      {row.source.paragraph !== null && <small>段落 {row.source.paragraph}</small>}
                      {row.source.source_label && <small>{row.source.source_label}</small>}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onJump(row)}
                    disabled={row.source.page === null}
                  >
                    <MapPin size={13} />
                    来源定位
                  </button>
                  {row.source.correction_reason && (
                    <small className="correction" title={row.source.correction_reason}>
                      含编号修正证据
                    </small>
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    className="review-button"
                    data-focus-key={`review:${row.id}`}
                    aria-label={`复核 ${row.display_id}`}
                    onClick={() => onReview(row)}
                  >
                    <MessageSquareText size={15} />
                    复核
                  </button>
                  <small className="review-state">
                    {row.review ? reviewLabels[row.review.decision] : '尚未复核'}
                  </small>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
