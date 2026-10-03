import { FileText, MapPin, MessageSquareText } from 'lucide-react';
import type { Activity, Compound } from '../../api/types';
import { confidenceLabels, reviewLabels } from '../../model/presentation';
import { groupActivities } from '../../model/results';
import { ActivityCell } from './ActivityCell';
import { RecognitionStatus } from './RecognitionDetails';
import { StructureCell } from './StructureCell';
import { AssayContexts } from './AssayContexts';

export function ResultRow({
  row,
  number,
  metrics,
  selected,
  focused,
  onSelect,
  onJump,
  onActivitySource,
  onCrop,
  onReview,
}: {
  row: Compound;
  number: number;
  metrics: string[];
  selected: boolean;
  focused: boolean;
  onSelect: () => void;
  onJump: (row: Compound) => void;
  onActivitySource: (activity: Activity) => void;
  onCrop: (row: Compound) => void;
  onReview: (row: Compound) => void;
}) {
  const contexts = groupActivities(row.activities, metrics);
  return (
    <tr key={row.id} data-compound={row.id} className={focused ? 'source-focused' : ''}>
      <td>
        <input
          type="checkbox"
          aria-label={`选择化合物 ${row.display_id}`}
          checked={selected}
          onChange={onSelect}
        />
      </td>
      <td className="row-number">{number}</td>
      <StructureCell row={row} onCrop={onCrop} />
      <AssayContexts
        contexts={contexts}
        emptyLabel={metrics.length ? '无活性数据' : '未选择指标'}
      />
      {metrics.map((metric) => (
        <ActivityCell
          key={metric}
          compound={row}
          metric={metric}
          contexts={contexts}
          onSource={onActivitySource}
        />
      ))}
      <td>
        <span
          className={`badge ${row.confidence.level}`}
          title={row.confidence.reason ?? '绑定证据依据未提供'}
        >
          {confidenceLabels[row.confidence.level]}
        </span>
        {row.confidence.score !== null && (
          <small className="confidence-score" title="仅为绑定证据分数，不是识别准确率">
            {String(row.confidence.score)}
          </small>
        )}
      </td>
      <td>
        <RecognitionStatus recognition={row.recognition} />
        {row.recognition?.quality_flag && row.recognition.quality_flag !== 'ok' && (
          <small className="recognition-flag" title={row.recognition.quality_flag}>
            {row.recognition.quality_flag}
          </small>
        )}
      </td>
      <td>
        <div className="source-cell">
          <FileText size={13} />
          <div>
            <span>{row.source.page === null ? '页码未知' : `第 ${row.source.page} 页`}</span>
            {row.source.paragraph !== null && <small>段落 {row.source.paragraph}</small>}
          </div>
        </div>
        <button
          type="button"
          className="link-button"
          onClick={() => onJump(row)}
          disabled={row.source.page === null}
        >
          <MapPin size={12} />
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
          <MessageSquareText size={14} />
          复核
        </button>
        <small className="review-state">
          {row.review ? reviewLabels[row.review.decision] : '未复核'}
        </small>
      </td>
    </tr>
  );
}
