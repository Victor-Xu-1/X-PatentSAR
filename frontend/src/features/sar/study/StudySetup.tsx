import { useCallback, useState } from 'react';
import type { Dataset, Region, SARJob } from '../../../api/sarTypes';
import { sarStudyApi } from '../../../api/sarStudyApi';
import { useTranslation } from '../../../i18n';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { MutationNotice } from '../MutationNotice';
import { useSARMutation } from '../useSARMutation';
import { useSARResource } from '../useSARResource';
import { newRequestId } from '../presentation';
import { ContextPicker } from './ContextPicker';
import { PolicyEditor } from './PolicyEditor';
import { StudyRegionEditor } from './StudyRegionEditor';
import { ConditionEditor } from './ConditionEditor';
import { declarationFromDraft, emptyCondition } from './conditionDraft';
import type { ConditionDraft } from './conditionDraft';
import { emptyPolicy, policyFromDraft } from './policyDraft';
import type { PolicyDraft } from './policyDraft';
export function StudySetup({
  dataset,
  active,
  disabled,
  scope,
  onJob,
}: {
  dataset: Dataset;
  active: boolean;
  disabled: boolean;
  scope: string;
  onJob: (job: SARJob) => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(dataset.title),
    [selected, setSelected] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Record<string, PolicyDraft>>({});
  const [conditionDrafts, setConditionDrafts] = useState<Record<string, ConditionDraft>>({});
  const [regionIds, setRegionIds] = useState<string[]>([]);
  const [coreIds, setCoreIds] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false),
    [candidateCount, setCandidateCount] = useState(8);
  const load = useCallback(
    (signal: AbortSignal) => sarStudyApi.profile(dataset.id, dataset.revision, signal),
    [dataset.id, dataset.revision],
  );
  const profile = useSARResource(
    'sar:profile:' + dataset.id + ':' + dataset.revision,
    active && !disabled,
    load,
  );
  const mutation = useSARMutation({
    active,
    scope: JSON.stringify([scope, dataset.id, dataset.revision]),
  });
  const ready = profile.validated && !disabled && !dataset.stale;
  const policies = selected.map((id) => policyFromDraft(id, drafts[id] ?? emptyPolicy()));
  const declarations = selected.map((id) => {
    const context = profile.data?.contexts.find((item) => item.id === id);
    const draft = conditionDrafts[id] ?? emptyCondition();
    return {
      enabled: draft.enabled,
      value: context ? declarationFromDraft(dataset, context, draft) : null,
    };
  });
  const valid =
    ready &&
    title.trim().length > 0 &&
    title.length <= 200 &&
    selected.length > 0 &&
    selected.length <= 8 &&
    policies.every(Boolean) &&
    declarations.every((item) => !item.enabled || item.value !== null) &&
    selected.every((id) => profile.data?.contexts.some((c) => c.id === id)) &&
    regionIds.length <= 12 &&
    regionIds.every((id) =>
      profile.data?.regions.some(
        (r) => r.id === id && r.dataset_revision === dataset.revision && r.kind !== 'core',
      ),
    ) &&
    coreIds.length <= 12 &&
    coreIds.every((id) =>
      profile.data?.regions.some(
        (r) => r.id === id && r.dataset_revision === dataset.revision && r.kind === 'core',
      ),
    );
  const reloadProfile = profile.reload;
  const saved = useCallback(
    (region: Region) => {
      reloadProfile();
      const update = region.kind === 'core' ? setCoreIds : setRegionIds;
      update((old) => (old.includes(region.id) ? old : [...old, region.id]));
    },
    [reloadProfile],
  );
  return (
    <section className="sar-panel sar-study-setup" aria-label={t('研究设置')}>
      <div className="sar-section-heading">
        <h2>{t('完整 SAR 研究')}</h2>
        <button type="button" disabled={!active || disabled} onClick={profile.reload}>
          {t('刷新')}
        </button>
      </div>
      {profile.loading && <Loading />}
      {profile.error && <SARFailure error={profile.error} onRetry={profile.reload} />}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!valid || mutation.locked) return;
          const documented = declarations.flatMap((item) => (item.value ? [item.value] : []));
          const payload = {
            title,
            request_id: newRequestId(),
            expected_dataset_revision: dataset.revision,
            policies: policies.filter((p) => p !== null),
            region_ids: [...regionIds],
            core_ids: [...coreIds],
            candidate_count: candidateCount,
            confirm_context: confirm,
            ...(documented.length ? { context_declarations: documented } : {}),
          };
          void mutation.run(
            () => sarStudyApi.start(dataset.id, payload),
            onJob,
            payload.request_id,
          );
        }}
      >
        <fieldset disabled={!ready || mutation.locked}>
          <div className="sar-form-grid">
            <label>
              {t('研究名称')}
              <input maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label>
              {t('候选数量')}
              <select
                value={candidateCount}
                onChange={(e) => setCandidateCount(Number(e.target.value))}
              >
                {[5, 6, 7, 8, 9, 10].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
          </div>
          {profile.data && (
            <ContextPicker
              contexts={profile.data.contexts}
              selected={selected}
              onSelect={(id, checked) => {
                setSelected((old) => (checked ? [...old, id] : old.filter((v) => v !== id)));
                setDrafts((old) => ({ ...old, [id]: old[id] ?? emptyPolicy() }));
              }}
            />
          )}
          {selected.map((id) => {
            const context = profile.data?.contexts.find((c) => c.id === id);
            return context ? (
              <div key={id} className="sar-policy-block">
                <PolicyEditor
                  key={id}
                  context={context}
                  draft={drafts[id] ?? emptyPolicy()}
                  onChange={(draft) => setDrafts((old) => ({ ...old, [id]: draft }))}
                />
                <ConditionEditor
                  dataset={dataset}
                  context={context}
                  draft={conditionDrafts[id] ?? emptyCondition()}
                  onChange={(draft) => setConditionDrafts((old) => ({ ...old, [id]: draft }))}
                />
              </div>
            ) : (
              <p key={id} role="alert">
                {t('实验条件已变化，请重新确认选择。')}
              </p>
            );
          })}
          {(['variable', 'core'] as const).map((kind) => {
            const ids = kind === 'core' ? coreIds : regionIds,
              update = kind === 'core' ? setCoreIds : setRegionIds;
            return (
              <details className="sar-compact" key={kind}>
                <summary>
                  {t(kind === 'core' ? '已确认核心（可选）' : '变化区域（可选）')} · {ids.length}/12
                </summary>
                <div className="sar-region-list">
                  {profile.data?.regions
                    .filter((r) => (r.kind ?? 'variable') === kind)
                    .map((region, index) => (
                      <label className="sar-checkbox" key={region.id}>
                        <input
                          type="checkbox"
                          checked={ids.includes(region.id)}
                          disabled={
                            region.dataset_revision !== dataset.revision ||
                            (ids.length >= 12 && !ids.includes(region.id))
                          }
                          onChange={(e) => {
                            const checked = e.target.checked;
                            update((old) =>
                              checked ? [...old, region.id] : old.filter((id) => id !== region.id),
                            );
                          }}
                        />
                        {region.name ?? 'R' + (index + 1)} ·{' '}
                        {t('已选原子：{indices}', { indices: region.atom_indices.join(', ') })}
                      </label>
                    ))}
                </div>
              </details>
            );
          })}
          <label className="sar-checkbox">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            {t('我仅确认缺失的实验条件允许比较；已知条件差异仍禁止比较。')}
          </label>
          <button className="primary" type="submit" disabled={!valid}>
            {t('运行完整研究')}
          </button>
          <small className="sar-hint">
            {t('无区域也可运行概览；不猜测等级、阈值或实验条件。')}
          </small>
        </fieldset>
      </form>
      <MutationNotice mutation={mutation} disabled={!ready} />
      {profile.data && (
        <StudyRegionEditor
          dataset={dataset}
          regions={profile.data.regions}
          active={active}
          disabled={!ready || mutation.locked}
          scope={scope}
          onSaved={saved}
        />
      )}
    </section>
  );
}
