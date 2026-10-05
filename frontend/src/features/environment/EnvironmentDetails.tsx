import type {
  EnvironmentCatalog,
  EnvironmentComponentId,
  EnvironmentSettings,
} from '../../api/environmentTypes';
import { Dialog } from '../../components/Dialog';
import { ComponentLibrary } from './ComponentLibrary';
import { InstallLocation } from './InstallLocation';

export function EnvironmentDetails({
  catalog,
  disabled,
  onClose,
  onInspect,
  onInstall,
  onSave,
}: {
  catalog: EnvironmentCatalog;
  disabled: boolean;
  onClose: () => void;
  onInspect: (ids: EnvironmentComponentId[]) => void;
  onInstall: (ids: EnvironmentComponentId[]) => void;
  onSave: (root: string, revision: number) => Promise<EnvironmentSettings | null>;
}) {
  return (
    <Dialog title="环境详情" onClose={onClose} wide>
      <div className="dialog-body environment-details">
        <ComponentLibrary
          components={catalog.components}
          disabled={disabled}
          onInspect={onInspect}
          onInstall={onInstall}
        />
        <details className="environment-location-editor">
          <summary>修改位置</summary>
          <InstallLocation settings={catalog.settings} disabled={disabled} onSave={onSave} />
        </details>
        <footer className="dialog-actions">
          <button type="button" onClick={onClose}>
            关闭
          </button>
        </footer>
      </div>
    </Dialog>
  );
}
