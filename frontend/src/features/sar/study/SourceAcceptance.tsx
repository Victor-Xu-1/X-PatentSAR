import type { Project } from '../../../api/types';
import { useTranslation } from '../../../i18n';

const labels = {
  accepted: '原提取：QA 通过',
  historical: '原提取：历史结果',
  failed: '原提取：未通过 QA',
  not_run: '原提取：尚未验收',
} as const;
export function SourceAcceptance({ source }: { source: Project['acceptance'] | null | undefined }) {
  const { t } = useTranslation();
  return (
    <div className="sar-source-acceptance">
      <span
        className={
          'sar-source-status ' + (source?.state === 'accepted' ? 'is-accepted' : 'is-review')
        }
      >
        {t(source ? labels[source.state] : '来源 QA 状态未记录')}
      </span>
      {source?.state !== 'accepted' && <small>{t('研究结果不改变原提取验收。')}</small>}
      {!!source?.errors.length && (
        <details>
          <summary>{t('核对详情')}</summary>
          <ul>
            {source.errors.map((error, index) => (
              <li key={index}>{error}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
