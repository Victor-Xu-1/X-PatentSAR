import { client } from '../../api';
import { ContractError, object, string } from '../../api/validation';

const decodeStructure = object({
  smiles: (input: unknown, path?: string): string | null => {
    if (input === null) return null;
    const value = string(input, path);
    if (!value || value.length > 2048 || /[\s|]/.test(value))
      throw new ContractError(path ?? '$.smiles');
    return value;
  },
});

/** A deadline also settles non-abortable SDK promises; late results stay ignored. */
async function withDeadline<T>(
  signal: AbortSignal,
  operation: (signal: AbortSignal) => Promise<T>,
  timeoutMessage: string,
): Promise<T> {
  signal.throwIfAborted();
  const controller = new AbortController();
  const relay = () => controller.abort(signal.reason);
  let rejectAbort: () => void = () => {};
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = () => reject(controller.signal.reason);
    controller.signal.addEventListener('abort', rejectAbort, { once: true });
  });
  signal.addEventListener('abort', relay, { once: true });
  const timer = setTimeout(() => controller.abort(new Error(timeoutMessage)), 15000);
  try {
    return await Promise.race([operation(controller.signal), aborted]);
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', relay);
    controller.signal.removeEventListener('abort', rejectAbort);
  }
}

export function boundedEditorOperation<T>(operation: () => Promise<T>, signal: AbortSignal) {
  return withDeadline(signal, operation, '绘图导出超时，请重新加载编辑器。');
}

/** MDL goes unchanged to the existing local chemistry authority, never to Indigo SMILES. */
export function convertMolfile(molfile: string, signal: AbortSignal): Promise<string | null> {
  if (
    typeof molfile !== 'string' ||
    !molfile ||
    new TextEncoder().encode(molfile).byteLength > 131072
  )
    return Promise.reject(new Error('结构超过支持的编辑范围，或绘图导出无效。'));
  return withDeadline(
    signal,
    async (requestSignal) => {
      const response = await client.mutate(
        '/chemistry/structure',
        'POST',
        { molfile },
        decodeStructure,
        { signal: requestSignal, timeoutMs: 15000 },
      );
      return response.smiles;
    },
    '结构转换超时，请重新加载编辑器。',
  );
}
