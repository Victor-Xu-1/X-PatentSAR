import type { Project } from '../../api/types';
import { useTranslation } from '../../i18n';

/** A source read failure is not an empty dataset or a task-stage failure. */
export function ProjectReadIssue({
  project,
  id,
  className = '',
}: {
  project: Project | null;
  id?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  if (!project?.read_error) return null;
  const label = t('结果数据需修复');
  return (
    <span
      id={id}
      className={`badge failed ${className}`}
      role="status"
      aria-label={label}
      title={project.read_error.message}
    >
      {label}
    </span>
  );
}
