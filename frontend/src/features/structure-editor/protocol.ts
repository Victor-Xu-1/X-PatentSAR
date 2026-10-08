import type { StructureChange } from '../results/correctionDraft';
import { UiError } from '../../i18n';

export const EDITOR_CHANNEL = 'x-patentsar.structure-editor.v1';
export interface EditorLoad {
  channel: typeof EDITOR_CHANNEL;
  kind: 'load';
  smiles: string;
  molfile: string | null;
}
export type EditorPayload =
  | { kind: 'ready' | 'loaded' | 'busy' | 'save' }
  | { kind: 'error'; message: string; recoverable: boolean; source?: string }
  | { kind: 'change'; value: StructureChange };
export type EditorMessage = EditorPayload & { channel: typeof EDITOR_CHANNEL };

export function readEditorLoad(data: unknown): EditorLoad {
  const row = data as Partial<EditorLoad> | null;
  if (
    !row ||
    row.channel !== EDITOR_CHANNEL ||
    row.kind !== 'load' ||
    typeof row.smiles !== 'string' ||
    row.smiles.length > 2048 ||
    !(row.molfile === null || (typeof row.molfile === 'string' && row.molfile.length <= 131072))
  )
    throw new UiError('结构加载消息无效。');
  return row as EditorLoad;
}
export function readEditorMessage(data: unknown): EditorMessage {
  if (typeof data !== 'object' || !data || Array.isArray(data))
    throw new UiError('结构编辑消息无效。');
  const row = data as Record<string, unknown>;
  if (row.channel !== EDITOR_CHANNEL) throw new UiError('结构编辑通道不匹配。');
  if (row.kind === 'ready' || row.kind === 'loaded' || row.kind === 'busy' || row.kind === 'save')
    return row as EditorMessage;
  if (
    row.kind === 'error' &&
    typeof row.message === 'string' &&
    row.message.length <= 1000 &&
    (row.source === undefined || (typeof row.source === 'string' && row.source.length <= 1000)) &&
    typeof row.recoverable === 'boolean'
  )
    return row as EditorMessage;
  if (row.kind === 'change') {
    const value = row.value as Partial<StructureChange> | null;
    if (
      value &&
      typeof value.smiles === 'string' &&
      value.smiles.length <= 2048 &&
      (value.molfile === null ||
        (typeof value.molfile === 'string' && value.molfile.length <= 131072)) &&
      typeof value.graphKey === 'string' &&
      value.graphKey.length <= 2048 &&
      typeof value.graphChanged === 'boolean'
    )
      return row as EditorMessage;
  }
  throw new UiError('结构编辑数据无效，未接受修改。');
}
