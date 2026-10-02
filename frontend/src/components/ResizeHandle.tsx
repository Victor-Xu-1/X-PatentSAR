import { useEffect, useRef, useState } from 'react';

interface Drag {
  id: number;
  x: number;
  initial: number;
  next: number;
}

export function ResizeHandle({
  label,
  controls,
  value,
  min,
  max,
  keyStep = 8,
  resetValue,
  className = '',
  valueText,
  onBegin,
  fromPointer,
  onPreview,
  onCommit,
}: {
  label: string;
  controls?: string;
  value: number;
  min: number;
  max: number;
  keyStep?: number;
  resetValue: number;
  className?: string;
  valueText?: string;
  onBegin?: () => number;
  fromPointer?: (delta: number, initial: number) => number;
  onPreview: (value: number | null) => void;
  onCommit: (value: number) => void;
}) {
  const drag = useRef<Drag | null>(null);
  const reportPreview = useRef(onPreview);
  const [moving, setMoving] = useState(false);
  useEffect(() => {
    reportPreview.current = onPreview;
  }, [onPreview]);
  useEffect(
    () => () => {
      if (drag.current) {
        drag.current = null;
        reportPreview.current(null);
      }
    },
    [],
  );
  const bounded = (next: number) =>
    Number.isFinite(next) ? Math.min(max, Math.max(min, Math.round(next))) : null;
  function finish(commit: boolean, element: HTMLInputElement) {
    const current = drag.current;
    if (!current) return;
    drag.current = null;
    setMoving(false);
    if (commit && current.next !== current.initial) onCommit(current.next);
    onPreview(null);
    if (element.hasPointerCapture?.(current.id)) element.releasePointerCapture(current.id);
  }
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={1}
      value={value}
      aria-label={label}
      aria-controls={controls}
      aria-orientation="horizontal"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={valueText ?? `${value} 像素`}
      title="拖动调整宽度；方向键调整，双击重置，Escape 取消拖动"
      className={`resize-handle ${className}${moving ? ' dragging' : ''}`}
      onChange={(event) => {
        const next = bounded(Number(event.target.value));
        if (next !== null) onCommit(next);
      }}
      onDoubleClick={() => {
        onBegin?.();
        onCommit(resetValue);
        onPreview(null);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && drag.current) {
          event.preventDefault();
          event.stopPropagation();
          finish(false, event.currentTarget);
          return;
        }
        if (!['Home', 'End', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        const initial = onBegin?.() ?? value;
        const next = bounded(
          event.key === 'Home'
            ? min
            : event.key === 'End'
              ? max
              : initial + (event.key === 'ArrowLeft' ? -keyStep : keyStep),
        );
        if (next !== null) onCommit(next);
        onPreview(null);
      }}
      onPointerDown={(event) => {
        if (event.button !== 0 || event.isPrimary === false || drag.current) return;
        const initial = bounded(onBegin?.() ?? value);
        if (initial === null || !Number.isFinite(event.clientX)) return;
        event.preventDefault();
        event.currentTarget.focus();
        drag.current = { id: event.pointerId, x: event.clientX, initial, next: initial };
        setMoving(true);
        event.currentTarget.setPointerCapture?.(event.pointerId);
      }}
      onPointerMove={(event) => {
        const current = drag.current;
        if (!current || current.id !== event.pointerId) return;
        const delta = event.clientX - current.x;
        const next = bounded(fromPointer?.(delta, current.initial) ?? current.initial + delta);
        if (next === null || next === current.next) return;
        current.next = next;
        onPreview(next);
      }}
      onPointerUp={(event) => {
        if (drag.current?.id === event.pointerId) finish(true, event.currentTarget);
      }}
      onPointerCancel={(event) => {
        if (drag.current?.id === event.pointerId) finish(false, event.currentTarget);
      }}
      onLostPointerCapture={(event) => {
        if (drag.current?.id === event.pointerId) finish(false, event.currentTarget);
      }}
    />
  );
}
