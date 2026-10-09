import { ApiError } from '../../api/errors';
import { UiError } from '../../i18n';

/** Only application-owned copy is localized. Model/SDK/server diagnostics stay raw. */
export function editorErrorSource(error: Error): { source?: string } {
  if (!(error instanceof UiError)) return {};
  if (!(error instanceof ApiError)) return { source: error.source };
  // HTTP failures contain server-owned diagnostics. Status 0 and these exact
  // codes originate in the existing browser client's transport, not the server.
  return error.status === 0 && ['network_error', 'timeout', 'response_limit'].includes(error.code)
    ? { source: error.source }
    : {};
}
