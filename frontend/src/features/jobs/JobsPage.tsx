import { useState, type ComponentProps } from 'react';
import { useTranslation } from '../../i18n';
import { Tabs } from '../../components/Tabs';
import { ExtractionJobs } from './ExtractionJobs';
import { SARHistoryPanel } from './SARHistoryPanel';

export type JobModule = 'patent' | 'sar';
export function JobsPage({
  module,
  onModule,
  onOpenSAR,
  ...extraction
}: ComponentProps<typeof ExtractionJobs> & {
  module?: JobModule;
  onModule?: (value: JobModule) => void;
  onOpenSAR?: (datasetId: string, jobId: string) => void;
}) {
  const { t } = useTranslation();
  const [localModule, setLocalModule] = useState<JobModule>('patent');
  const selected = module ?? localModule;
  return (
    <section className="management-page jobs-page" aria-labelledby="jobs-heading">
      <header className="page-header">
        <h1 id="jobs-heading">{t('任务记录')}</h1>
      </header>
      <div className="jobs-module-tabs">
        <Tabs<JobModule>
          label="任务模块"
          value={selected}
          tabs={[
            { value: 'patent', label: '专利提取' },
            { value: 'sar', label: 'SAR 分析' },
          ]}
          onChange={(value) => {
            setLocalModule(value);
            onModule?.(value);
          }}
        />
      </div>
      <div role="tabpanel" aria-label={t('专利提取')} hidden={selected !== 'patent'}>
        <ExtractionJobs {...extraction} active={selected === 'patent'} />
      </div>
      <div role="tabpanel" aria-label={t('SAR 分析')} hidden={selected !== 'sar'}>
        <SARHistoryPanel active={selected === 'sar'} onOpen={onOpenSAR} />
      </div>
    </section>
  );
}
