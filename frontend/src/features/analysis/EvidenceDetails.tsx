import { useState } from 'react';
import { AcceptanceFindings } from '../results/AcceptanceFindings';

export function EvidenceDetails({
  errors,
  pages,
  limitations,
  onSource,
}: {
  errors: readonly string[];
  pages: readonly number[];
  limitations: readonly string[];
  onSource: (page: number) => void;
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  return (
    <div className="evidence-details">
      {errors.length > 0 && (
        <div className="evidence-findings">
          <AcceptanceFindings errors={errors} open={false} />
        </div>
      )}
      <details
        className="evidence-sources"
        onToggle={(event) => setSourcesOpen(event.currentTarget.open)}
      >
        <summary>原始来源页 · {pages.length}</summary>
        {sourcesOpen && (
          <div className="evidence-source-pages">
            {pages.length ? (
              pages.map((page) => (
                <button
                  type="button"
                  key={page}
                  aria-label={`查看来源第 ${page} 页`}
                  onClick={() => onSource(page)}
                >
                  第 {page} 页
                </button>
              ))
            ) : (
              <p className="muted">来源页未提供</p>
            )}
          </div>
        )}
      </details>
      <details className="evidence-limitations">
        <summary>统计范围与证据边界</summary>
        <p>
          仅聚合原始字段与来源；不是 LLM
          摘要，不推断机制或疗效，不合并不同单位/靶点，不改变正式验收。
        </p>
        {limitations.length > 0 && (
          <ul>
            {limitations.map((limit, index) => (
              <li key={index}>{limit}</li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}
