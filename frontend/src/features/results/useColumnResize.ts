import { useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { ResultColumn } from '../../model/resultColumns';

type Widths = Record<string, number>;

export function useColumnResize(
  columns: ResultColumn[],
  table: RefObject<HTMLTableElement | null>,
) {
  const [committed, setCommitted] = useState<Widths>({});
  const [preview, setPreview] = useState<Widths | null>(null);
  const baseline = useRef<Widths>({});
  const widths = preview ?? committed;
  const resized = Object.keys(widths).length > 0;

  function begin(id: string): number {
    const headers = table.current?.tHead?.rows[0]?.cells;
    baseline.current = { ...committed };
    columns.forEach((item, index) => {
      const measured = headers?.[index]?.getBoundingClientRect().width;
      baseline.current[item.id] =
        measured !== undefined && Number.isFinite(measured) && measured > 0
          ? Math.min(item.max, Math.max(item.min, Math.round(measured)))
          : (committed[item.id] ?? item.width);
    });
    return baseline.current[id]!;
  }

  return {
    resized,
    widths,
    totalWidth: columns.reduce((total, item) => total + (widths[item.id] ?? item.width), 0),
    begin,
    preview: (id: string, value: number | null) =>
      setPreview(value === null ? null : { ...baseline.current, [id]: value }),
    commit: (id: string, value: number) => {
      setCommitted({ ...baseline.current, [id]: value });
      setPreview(null);
    },
  };
}
