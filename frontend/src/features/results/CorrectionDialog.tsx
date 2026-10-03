import type { Compound } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { ActivityEditor } from './ActivityEditor';
import { useCorrection } from './useCorrection';

export function CorrectionDialog({
  projectId,
  compound,
  onClose,
  onSaved,
  onReview,
}: {
  projectId: string;
  compound: Compound;
  onClose: () => void;
  onSaved: () => void;
  onReview: () => void;
}) {
  const edit = useCorrection(projectId, compound.id, onSaved);
  const { document, draft, busy, blocked } = edit;
  return (
    <Dialog title={`在线修正 · ${compound.display_id}`} onClose={onClose} busy={busy} wide>
      {!document || !draft ? (
        <div className="dialog-body">
          {edit.resource.error ? (
            <ErrorNotice error={edit.resource.error} onRetry={edit.resource.reload} />
          ) : edit.resource.loading ? (
            <Loading label="正在读取原始值与已保存修正…" />
          ) : (
            <Empty title="修正数据尚不可用" description="刷新后重试，不会修改原始专利。" />
          )}
        </div>
      ) : (
        <form
          className="dialog-body correction-form"
          onSubmit={(event) => {
            event.preventDefault();
            void edit.save();
          }}
        >
          <p className="muted">
            修正单独保存，原文和原始提取不变。修改 SMILES 后自动重算本行六项指标。
          </p>
          {(document.stale || blocked) && (
            <p className="conflict">原始数据或保存版本有变化。草稿保留，读取当前版本后再保存。</p>
          )}
          <label className="form-field">
            化合物编号
            <input
              data-initial-focus
              aria-label="修正化合物编号"
              required
              maxLength={200}
              value={draft.displayId}
              disabled={busy || blocked}
              onChange={(event) => edit.setDraft({ ...draft, displayId: event.target.value })}
            />
          </label>
          <label className="form-field">
            SMILES
            <textarea
              aria-label="修正 SMILES"
              rows={3}
              maxLength={2048}
              value={draft.smiles}
              disabled={busy || blocked}
              placeholder="输入有效 SMILES；无可靠结构时留空"
              onChange={(event) => edit.setDraft({ ...draft, smiles: event.target.value })}
            />
          </label>
          <ActivityEditor
            values={draft.activities}
            disabled={busy || blocked}
            onChange={(activities) => edit.setDraft({ ...draft, activities })}
          />
          <details className="correction-original">
            <summary>原始值 / 当前已保存值 · 修订 {document.revision}</summary>
            <div className="revision-comparison">
              <strong>原始提取</strong>
              <pre>{JSON.stringify(document.original, null, 2)}</pre>
            </div>
            <div className="revision-comparison">
              <strong>当前已保存</strong>
              <pre>{JSON.stringify(document.values, null, 2)}</pre>
            </div>
          </details>
          {edit.message && <output className="info-banner">{edit.message}</output>}
          {edit.error && <ErrorNotice error={edit.error} />}
          {blocked && (
            <button type="button" disabled={busy} onClick={() => void edit.readLatest()}>
              检查已保存状态并保留草稿
            </button>
          )}
          <footer className="dialog-actions">
            <button type="button" disabled={busy} onClick={onReview}>
              复核注记
            </button>
            <button
              type="button"
              disabled={busy || blocked || !document.has_changes}
              onClick={() => {
                if (window.confirm('恢复该行原始值？现有修正仍保留在修订记录中。'))
                  void edit.save(true);
              }}
            >
              恢复原始值
            </button>
            <button type="button" disabled={busy} onClick={onClose}>
              取消
            </button>
            <button type="submit" className="primary" disabled={busy || blocked}>
              {busy ? '正在保存…' : '保存修正'}
            </button>
          </footer>
        </form>
      )}
    </Dialog>
  );
}
