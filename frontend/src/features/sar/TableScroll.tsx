import type { ReactNode } from 'react';
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      className="sar-table-scroll"
      // Native horizontal table scrolling needs a keyboard focus target, as in ResultsTable.
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label={label}
    >
      {children}
    </div>
  );
}
