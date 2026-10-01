import type { AssayContext } from '../../model/results';

export function AssayContexts({
  contexts,
  emptyLabel,
}: {
  contexts: AssayContext[];
  emptyLabel: string;
}) {
  return (
    <td>
      <div className="assay-list">
        {contexts.map((context, contextIndex) => (
          <div className="assay-context" key={context.key}>
            {contexts.length > 1 && (
              <small className="context-number" aria-label={`实验 ${contextIndex + 1}`}>
                {contextIndex + 1}
              </small>
            )}
            <div>
              <strong title={context.target ?? '靶点未提供'}>
                {context.target ?? '靶点未提供'}
              </strong>
              <span title={context.assay ?? '实验未提供'}>{context.assay ?? '实验未提供'}</span>
            </div>
          </div>
        ))}
        {!contexts.length && <span className="muted">{emptyLabel}</span>}
      </div>
    </td>
  );
}
