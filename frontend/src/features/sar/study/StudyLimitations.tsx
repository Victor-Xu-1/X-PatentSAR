import { useTranslation } from '../../../i18n';
import { evidenceSummaries } from './evidencePresentation';
export function StudyLimitations({ warnings }: { warnings: string[] }) {
  const { t } = useTranslation();
  return (
    <details className="sar-compact sar-study-limitations">
      <summary>{t('研究限制与警告')}</summary>
      <p>{t('候选仅供实验优先级参考；骨架汇总不等于严格匹配，预测不替代实测。')}</p>
      <ul>
        {evidenceSummaries(warnings).map((summary) => (
          <li key={summary}>{t(summary)}</li>
        ))}
      </ul>
      <details className="sar-technical-evidence">
        <summary>{t('技术证据')}</summary>
        <ul>
          {warnings.map((code) => (
            <li key={code}>
              <code>{code}</code>
            </li>
          ))}
        </ul>
      </details>
    </details>
  );
}
