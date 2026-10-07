import type {
  EnvironmentCatalog,
  EnvironmentComponentId,
  EnvironmentSettings,
  EnvironmentStorageLocations,
} from '../../api/environmentTypes';
import type { ReactNode } from 'react';
import { Dialog } from '../../components/Dialog';
import { ComponentLibrary } from './ComponentLibrary';
import { StorageLocations } from './StorageLocations';

export function EnvironmentDetails({
  catalog,
  disabled,
  storageDisabled,
  busy,
  error,
  recovery,
  onClose,
  onInspect,
  onInstall,
  onSave,
}: {
  catalog: EnvironmentCatalog;
  disabled: boolean;
  storageDisabled: boolean;
  busy: boolean;
  error: Error | null;
  recovery: ReactNode;
  onClose: () => void;
  onInspect: (ids: EnvironmentComponentId[]) => void;
  onInstall: (ids: EnvironmentComponentId[]) => void;
  onSave: (
    locations: EnvironmentStorageLocations,
    revision: number,
  ) => Promise<EnvironmentSettings | null>;
}) {
  return (
    <Dialog
      title="存储位置"
      onClose={onClose}
      busy={busy}
      wide
      className="environment-details-dialog"
    >
      <StorageLocations
        settings={catalog.settings}
        disabled={storageDisabled}
        busy={busy}
        requestError={error}
        onSave={onSave}
        onClose={onClose}
      >
        {recovery}
        <details className="environment-component-details">
          <summary>环境详情</summary>
          <ComponentLibrary
            components={catalog.components}
            disabled={disabled}
            onInspect={onInspect}
            onInstall={onInstall}
          />
        </details>
      </StorageLocations>
    </Dialog>
  );
}
