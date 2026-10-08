import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from '../src/api';
import { JobActions } from '../src/features/jobs/JobActions';
import { LLMApiPanel } from '../src/features/llm/LLMApiPanel';
import { project } from '../tests/fixtures';
import { recoveryJob } from '../tests/llm-recovery-fixtures';
import '../src/styles/tokens.css';
import '../src/styles/base.css';
import '../src/styles/workflow.css';
import '../src/styles/dialogs.css';
import '../src/styles/management.css';
import '../src/styles/tasks.css';
import '../src/styles/responsive.css';

// A new test-only page/context: no application startup, patents, private state,
// cookies or credentials are copied from the user's running workbench.
function IsolatedRecoveryPage() {
  const [job, setJob] = useState({
    ...recoveryJob,
    stages: recoveryJob.stages.map((stage) =>
      stage.name === 'bind' ? { ...stage, repair: { regions: 7, unresolved: 2 } } : stage,
    ),
  });
  const query = new URLSearchParams(window.location.search);
  if (query.get('view') === 'settings') return <LLMApiPanel />;
  return (
    <main className="management-page jobs-page">
      <h1>隔离的恢复界面验证</h1>
      <article className="job-card">
        <div className="job-card-body">
          <JobActions
            project={project}
            job={job}
            ready
            compact={query.has('compact')}
            onChange={() => {
              void api.job(job.id, new AbortController().signal).then(setJob);
            }}
          />
        </div>
      </article>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <IsolatedRecoveryPage />
  </StrictMode>,
);
