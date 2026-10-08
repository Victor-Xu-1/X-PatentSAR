import type { Dataset, Molecule } from '../../api/sarTypes';
import { useTranslation } from '../../i18n';
import { sourceHash } from './presentation';
export function SourceLinks({ dataset, molecule }: { dataset: Dataset; molecule?: Molecule }) {
  const { t } = useTranslation();
  const project = sourceHash(dataset, molecule);
  const pages = Array.from(
    new Set([
      ...(molecule?.source_page ? [molecule.source_page] : []),
      ...(molecule?.observations.flatMap((o) =>
        o.source_kind === 'patent' && o.source_page ? [o.source_page] : [],
      ) ?? []),
    ]),
  );
  return (
    <span className="sar-source-links">
      {project && <a href={project}>{t('来源项目链接')}</a>}
      {project &&
        pages.map((page) => (
          <a key={page} href={sourceHash(dataset, molecule, page)!}>
            {t('原文第 {page} 页', { page })}
          </a>
        ))}
      {molecule && (!project || !pages.length) && <small>{t('未提供原文页码')}</small>}
    </span>
  );
}
