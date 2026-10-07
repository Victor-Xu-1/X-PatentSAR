import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/tokens.css';
import './styles/base.css';
import './styles/resizing.css';
import './styles/shell.css';
import './styles/workspace.css';
import './styles/workflow.css';
import './styles/results.css';
import './styles/table.css';
import './styles/activity-strength.css';
import './styles/pdf.css';
import './styles/dialogs.css';
import './styles/management.css';
import './styles/tasks.css';
import './styles/analysis.css';
import './styles/environment.css';
import './styles/environment-progress.css';
import './styles/responsive.css';

const root = document.getElementById('root');
if (!root) throw new Error('Application root is missing');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
