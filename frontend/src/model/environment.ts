import { getLocale, UiError, t } from '../i18n';
import type {
  EnvironmentComponent,
  EnvironmentComponentId,
  EnvironmentOperation,
} from '../api/environmentTypes';
import { environmentComponentIds } from '../api/environmentTypes';
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
// Reviewed catalog copy is selected by fixed IDs, never arbitrary server text.
const componentCopy: Record<EnvironmentComponentId, { name: string; description: string }> = {
  installer: {
    name: '受管安装工具',
    description: '本软件专属 uv；不依赖或修改全局工具。',
  },
  base: {
    name: '基础提取环境',
    description: '单一 Python 3.12 PDF、RapidOCR 和 RDKit 运行环境。',
  },
  decimer: {
    name: 'DECIMER 结构环境',
    description:
      'Python 3.10.20 / DECIMER 2.8.0 / Segmentation 1.5.0 / TF 2.15.1 / NumPy 1.26.4，强制 CPU。',
  },
  'decimer-models': {
    name: 'DECIMER 模型权重',
    description:
      '专利印刷 OCSR 和分割权重；按需安装，不下载未使用的手绘模型。加载检查不是识别准确性验收。',
  },
  admet: {
    name: 'ADMET CPU 环境',
    description: '独立 Python 3.12 / ADMET-AI 2.0.1 / Chemprop 2 / CPU Torch；不是实验测量。',
  },
  'admet-models': {
    name: 'ADMET 模型权重',
    description: '十个官方 pt 模型及端点元数据；不复制或使用 DrugBank 参考集。',
  },
  molscribe: {
    name: '本地手性兜底环境',
    description: '受限 CPU 兜底；仅在主模型丢失手性且连接图一致时使用，不并行常驻。',
  },
  'molscribe-models': {
    name: '本地手性兜底模型',
    description: '固定官方模型，加载检查不等于预测准确性验收。',
  },
};
export function environmentComponentName(component: EnvironmentComponent): string {
  return getLocale() !== 'zh-CN' && Object.hasOwn(componentCopy, component.id)
    ? t(componentCopy[component.id].name)
    : component.name;
}
export function environmentComponentDescription(component: EnvironmentComponent): string {
  return getLocale() !== 'zh-CN' && Object.hasOwn(componentCopy, component.id)
    ? t(componentCopy[component.id].description)
    : component.description;
}
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
    throw new UiError('安装目录必须是服务端批准的本地目录，不接受 C 盘、UNC、网络地址或命令。');
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
    throw new UiError('安装目录须位于服务端批准根目录内，不能包含路径跳转。');
  return root;
}
export function selectedEnvironmentComponents(
  components: EnvironmentComponent[],
  ids: EnvironmentComponentId[],
): EnvironmentComponent[] {
  const limit = environmentComponentIds.length;
  const inventory = new Map(components.map((component) => [component.id, component]));
  if (
    !ids.length ||
    ids.length > limit ||
    new Set(ids).size !== ids.length ||
    components.length > limit ||
    inventory.size !== components.length ||
    components.some((component) => !environmentComponentIds.includes(component.id))
  )
    throw new UiError('组件依赖目录无效或超出支持组件范围，请刷新后重新选择安装组合。');
  const selected: EnvironmentComponent[] = [];
  const visiting = new Set<EnvironmentComponentId>(),
    complete = new Set<EnvironmentComponentId>();
  function visit(id: EnvironmentComponentId) {
    if (complete.has(id)) return;
    const component = inventory.get(id);
    if (!component || !environmentComponentIds.includes(id))
      throw new UiError('组件依赖 {id} 未在服务端目录中声明，不能确认安装。', { id });
    if (visiting.has(id)) throw new UiError('服务端组件依赖存在循环，不能确认安装。');
    const dependencies = component.dependencies;
    if (
      !Array.isArray(dependencies) ||
      dependencies.length > limit ||
      new Set(dependencies).size !== dependencies.length
    )
      throw new UiError('服务端组件依赖元数据缺失、重复或超出支持组件范围。');
    if (dependencies.includes(id)) throw new UiError('服务端组件依赖不能包含自身。');
    visiting.add(id);
    for (const dependency of dependencies) visit(dependency);
    visiting.delete(id);
    complete.add(id);
    selected.push(component);
  }
  for (const id of ids) visit(id);
  return selected;
}
export function environmentBytes(value: number | null): string {
  if (value === null) return t('未报告');
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
