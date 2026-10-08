import { UiError } from '../../i18n';
import type { EnvironmentSettings, EnvironmentStorageLocations } from '../../api/environmentTypes';
import { normalizeInstallRoot } from '../../model/environment';

export const storageLocationFields = [
  { key: 'install_root', label: '集成环境安装目录', allowed: 'allowed_root' },
  { key: 'upload_root', label: '上传文件目录', allowed: 'allowed_data_root' },
  { key: 'result_root', label: '生成结果目录', allowed: 'allowed_data_root' },
] as const;

export function storageLocations(
  settings: EnvironmentStorageLocations,
): EnvironmentStorageLocations {
  return {
    install_root: settings.install_root,
    upload_root: settings.upload_root,
    result_root: settings.result_root,
  };
}

export function sameStorageLocations(
  left: EnvironmentStorageLocations,
  right: EnvironmentStorageLocations,
): boolean {
  return storageLocationFields.every(({ key }) => left[key] === right[key]);
}

export function normalizeStorageLocations(
  draft: EnvironmentStorageLocations,
  settings: EnvironmentSettings,
): EnvironmentStorageLocations {
  const normalized = storageLocations(draft);
  for (const { key, label, allowed } of storageLocationFields) {
    // Preserve current server values verbatim; legacy ownership is verified by the backend.
    if (draft[key] === settings[key]) continue;
    try {
      normalized[key] = normalizeInstallRoot(draft[key], settings[allowed]);
    } catch {
      throw new UiError(
        `${label}须位于服务端批准的本地目录范围 {root} 内，不能包含路径跳转、网络地址或命令。`,
        { root: settings[allowed] },
      );
    }
  }
  return normalized;
}
