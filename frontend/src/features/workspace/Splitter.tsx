import { useRef, useState } from 'react';
import type { RefObject } from 'react';
import { normalizeLayout, resizeFromPointer } from '../../model/layout';

export function Splitter({
  width,
  container,
  onPreview,
  onCommit,
}: {
  width: number;
  container: RefObject<HTMLDivElement | null>;
  onPreview: (width: number | null) => void;
  onCommit: (width: number) => void;
}) {
  const drag = useRef<{ id: number; width: number } | null>(null);
  const [moving, setMoving] = useState(false);
  return (
    <input
      type="range"
      min={20}
      max={55}
      step={1}
      value={width}
      className={`workspace-divider${moving ? ' dragging' : ''}`}
      onChange={(e) => onCommit(Number(e.target.value))}
      aria-label="调整原文与结果宽度"
      aria-controls="workspace-source workspace-results"
      aria-orientation="horizontal"
      aria-valuemin={20}
      aria-valuemax={55}
      aria-valuenow={width}
      aria-valuetext={`原文 ${width}%，结果 ${100 - width}%`}
      title="拖动调整；方向键每次 2%，Home/End 到边界"
      onKeyDown={(e) => {
        const next =
          e.key === 'Home'
            ? 20
            : e.key === 'End'
              ? 55
              : e.key === 'ArrowLeft'
                ? width - 2
                : e.key === 'ArrowRight'
                  ? width + 2
                  : null;
        if (next !== null) {
          e.preventDefault();
          onCommit(normalizeLayout({ pdfWidth: next }).pdfWidth);
        }
      }}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.focus();
        drag.current = { id: e.pointerId, width };
        setMoving(true);
        e.currentTarget.setPointerCapture?.(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!drag.current || drag.current.id !== e.pointerId) return;
        const rect = container.current?.getBoundingClientRect();
        const next = rect ? resizeFromPointer(e.clientX, rect) : null;
        if (next !== null) {
          drag.current.width = next;
          onPreview(next);
        }
      }}
      onPointerUp={(e) => {
        if (drag.current?.id !== e.pointerId) return;
        const next = drag.current.width;
        drag.current = null;
        setMoving(false);
        onCommit(next);
        onPreview(null);
        e.currentTarget.releasePointerCapture?.(e.pointerId);
      }}
      onPointerCancel={() => {
        drag.current = null;
        setMoving(false);
        onPreview(null);
      }}
      onLostPointerCapture={() => {
        drag.current = null;
        setMoving(false);
        onPreview(null);
      }}
    />
  );
}
