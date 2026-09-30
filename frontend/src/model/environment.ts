import type {
  EnvironmentComponent,
  EnvironmentComponentId,
  EnvironmentOperation,
} from '../api/environmentTypes';
export const environmentGroups = {
  tools: '安装工具',
  base: '基础运行环境',
  structure: '结构识别',
  admet: 'ADMET 分析',
} as const;
export const environmentStatusLabels = {
  unchecked: '未检测',
  checking: '检测中',
  missing: '缺失',
  partial: '不完整',
  ready: '可用',
  unconfigured: '未配置',
  incompatible: '版本不兼容',
  error: '检测失败',
} as const;
export function hasEnvironmentControlCharacters(value: string): boolean {
  return Array.from(value).some(
    (character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127,
  );
}
export function activeEnvironmentOperation(operation: EnvironmentOperation | null): boolean {
  return operation?.status === 'queued' || operation?.status === 'running';
}
export function normalizeInstallRoot(input: string, allowedRoot: string): string {
  if (
    input.length > 512 ||
    input.trim().startsWith('//') ||
    /[\\:]/.test(input) ||
    hasEnvironmentControlCharacters(input)
  )
    throw new Error('安装目录必须是服务端批准的本地目录，不接受 C 盘、UNC、网络地址或命令。');
  const root = input
    .trim()
    .replace(/\/+$/, '')
    .replace(/\/{2,}/g, '/');
  const allowed = allowedRoot.replace(/\/+$/, '');
  if (
    !root.startsWith('/') ||
    !allowed.startsWith('/') ||
    !allowed ||
    root.split('/').some((part) => part === '.' || part === '..') ||
    !(root === allowed || root.startsWith(`${allowed}/`))
  )
    throw new Error('安装目录须位于服务端批准根目录内，不能包含路径跳转。');
  return root;
}
export function selectedEnvironmentComponents(
  components: EnvironmentComponent[],
  ids: EnvironmentComponentId[],
): EnvironmentComponent[] {
  const selected = ids.map((id) => components.find((component) => component.id === id));
  if (!ids.length || new Set(ids).size !== ids.length || selected.some((item) => !item))
    throw new Error('组件目录已变化，请刷新后重新选择安装组合。');
  return selected as EnvironmentComponent[];
}
export function environmentBytes(value: number | null): string {
  if (value === null) return '未报告';
  if (value < 1024) return `${value} B`;
  const power = Math.min(3, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** power).toFixed(1)} ${['B', 'KiB', 'MiB', 'GiB'][power]}`;
}
export function safeEnvironmentSource(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}
