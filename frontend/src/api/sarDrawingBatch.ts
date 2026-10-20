/** Pending passive reads only: no retained results, scientific queue or alternate renderer. */
import { ApiError } from './errors';
import { ContractError } from './validation';
import type { StudyDrawing, StudyDrawingKind } from './sarStudyTypes';
import type { DrawingEntry, DrawingSelection } from './sarDrawingBatchDecoder';

type ReadBatch = (
  selection: DrawingSelection,
  keys: string[],
  signal: AbortSignal,
) => Promise<DrawingEntry[]>;
type Subscriber = {
  resolve: (drawing: StudyDrawing) => void;
  reject: (error: unknown) => void;
  cleanup: () => void;
};
type Entry = {
  key: string;
  id: string;
  selection: DrawingSelection;
  subscribers: Set<Subscriber>;
  work?: Work;
};
type Work = { entries: Entry[]; controller: AbortController };
const abortError = () => new DOMException('Drawing request cancelled', 'AbortError');

export function createDrawingBatch(read: ReadBatch) {
  const pending = new Map<string, Entry>(),
    queue: Work[] = [];
  let scheduled = false,
    active = 0;
  const live = (entry: Entry) => entry.subscribers.size > 0;
  function forget(entry: Entry) {
    if (pending.get(entry.key) === entry) pending.delete(entry.key);
  }
  function finish(entry: Entry, drawing: StudyDrawing | null, error?: unknown) {
    forget(entry);
    for (const subscriber of entry.subscribers) {
      subscriber.cleanup();
      if (drawing) subscriber.resolve(drawing);
      else subscriber.reject(error);
    }
    entry.subscribers.clear();
  }
  function enqueue(entries: Entry[]) {
    if (!entries.length) return;
    const work = { entries, controller: new AbortController() };
    entries.forEach((entry) => {
      entry.work = work;
    });
    queue.push(work);
  }
  async function execute(work: Work) {
    const entries = work.entries.filter(live);
    if (!entries.length) return;
    try {
      const items = await read(
        entries[0]!.selection,
        entries.map((entry) => entry.id),
        work.controller.signal,
      );
      items.forEach((item, index) => {
        const error = item.error;
        finish(
          entries[index]!,
          item.result,
          error ? new ApiError(error.status, error.code, error.message) : undefined,
        );
      });
    } catch (error) {
      // Only an explicit byte-budget refusal permits subdivision. 32 -> ... -> 1;
      // changed receipts, authentication and other failures are never replayed here.
      const remaining = entries.filter(live);
      if (
        error instanceof ApiError &&
        error.status === 413 &&
        error.code === 'sar_drawing_batch_large' &&
        entries.length > 1 &&
        remaining.length > 0
      ) {
        const middle = Math.ceil(remaining.length / 2);
        enqueue(remaining.slice(0, middle));
        enqueue(remaining.slice(middle));
      } else entries.forEach((entry) => finish(entry, null, error));
    }
  }
  function pump() {
    while (active < 2 && queue.length) {
      const work = queue.shift()!;
      if (!work.entries.some(live)) continue;
      active++;
      void execute(work).finally(() => {
        active--;
        pump();
      });
    }
  }
  function flush() {
    scheduled = false;
    const groups = new Map<string, Entry[]>();
    for (const entry of pending.values()) {
      if (entry.work || !live(entry)) continue;
      const key = JSON.stringify(entry.selection),
        group = groups.get(key) ?? [];
      group.push(entry);
      groups.set(key, group);
    }
    for (const group of groups.values())
      for (let i = 0; i < group.length; i += 32) enqueue(group.slice(i, i + 32));
    pump();
  }
  return (
    job: string,
    kind: StudyDrawingKind,
    id: string,
    signal: AbortSignal,
    region = '',
  ): Promise<StudyDrawing> => {
    if (
      !job ||
      !id ||
      id.length > 200 ||
      region.length > 200 ||
      !['molecule', 'scaffold', 'fragment'].includes(kind)
    )
      return Promise.reject(new ContractError('$.study_drawing_selector'));
    if (signal.aborted) return Promise.reject(abortError());
    const selection = { job, kind, region },
      key = JSON.stringify([job, kind, region, id]);
    let entry = pending.get(key);
    if (!entry) {
      entry = { key, id, selection, subscribers: new Set() };
      pending.set(key, entry);
    }
    const owned = entry;
    const promise = new Promise<StudyDrawing>((resolve, reject) => {
      const subscriber: Subscriber = {
        resolve,
        reject,
        cleanup: () => signal.removeEventListener('abort', cancel),
      };
      function cancel() {
        owned.subscribers.delete(subscriber);
        subscriber.cleanup();
        reject(abortError());
        if (!live(owned)) {
          forget(owned);
          if (owned.work && !owned.work.entries.some(live)) owned.work.controller.abort();
        }
      }
      owned.subscribers.add(subscriber);
      signal.addEventListener('abort', cancel, { once: true });
    });
    if (!scheduled) {
      scheduled = true;
      queueMicrotask(flush);
    }
    return promise;
  };
}
