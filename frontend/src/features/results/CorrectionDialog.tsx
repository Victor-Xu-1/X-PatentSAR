import { useState } from 'react';
import type { ActivityColumn, Compound } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { ActivityEditor } from './ActivityEditor';
import { PropertyEditor } from './PropertyEditor';
import StructureEditor from './StructureEditor';
import { changeStructureDraft } from './correctionDraft';
import { useCorrection } from './useCorrection';
import '../../styles/correction.css';

export function CorrectionDialog({
  projectId,
  compound,
  activityColumns = [],
  onClose,
  onSaved,
}: {
  projectId: string;
  compound: Compound;
  activityColumns?: ActivityColumn[] | undefined;
  onClose: () => void;
  onSaved: () => void;
}) {
  const edit = useCorrection(projectId, compound, activityColumns, onSaved);
  const { document, draft, busy, blocked } = edit;
  const [editorReady, setEditorReady] = useState(false);
  return (
    <Dialog
      title={`修正 · ${compound.display_id}`}
      onClose={onClose}
      busy={busy}
      wide
      className="correction-dialog"
    >
      {!document || !draft ? (
        <div className="dialog-body">
          {edit.resource.error ? (
            <ErrorNotice error={edit.resource.error} onRetry={edit.resource.reload} />
          ) : edit.resource.loading ? (
            <Loading label="正在读取数据…" />
          ) : (
            <Empty title="修正数据不可用" description="刷新后重试。" />
          )}
        </div>
      ) : (
        <form
          className="dialog-body correction-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (editorReady) void edit.save();
          }}
        >
          {(document.stale || blocked) && (
            <p className="conflict">保存版本或原始数据已变化，草稿保留。请先读取当前版本。</p>
          )}
          <div className="correction-editor-layout">
            <div className="correction-structure">
              <StructureEditor
                smiles={draft.smiles}
                molfile={draft.molfile}
                disabled={busy || blocked}
                onReady={setEditorReady}
                onSave={() => {
                  if (editorReady) void edit.save();
                }}
                onChange={(value) => edit.setDraft(changeStructureDraft(draft, value))}
              />
            </div>
            <div className="correction-fields">
              <label className="form-field">
                Compound
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
              <ActivityEditor
                values={draft.activities}
                disabled={busy || blocked}
                onChange={(activities) => edit.setDraft({ ...draft, activities })}
              />
              <PropertyEditor
                values={draft.properties}
                disabled={busy || blocked}
                onChange={(properties) => edit.setDraft({ ...draft, properties })}
              />
            </div>
          </div>
          {edit.message && <output className="info-banner">{edit.message}</output>}
          {edit.error && <ErrorNotice error={edit.error} />}
          {blocked && (
            <button type="button" disabled={busy} onClick={() => void edit.readLatest()}>
              检查已保存状态并保留草稿
            </button>
          )}
          <footer className="dialog-actions">
            <button type="button" disabled={busy} onClick={onClose}>
              取消
            </button>
            <button type="submit" className="primary" disabled={busy || blocked || !editorReady}>
              {busy ? '正在保存…' : '保存修正'}
            </button>
          </footer>
        </form>
      )}
    </Dialog>
  );
}
