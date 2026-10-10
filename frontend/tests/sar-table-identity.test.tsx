import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setLocale, t } from '../src/i18n';
import { StudyRowTable, studyColumns } from '../src/features/sar/study/StudyRowTable';
import { studyContext, studyRow } from './sar-fixtures';

beforeEach(() => setLocale('en'));

function table(hidden: string[] = []) {
  return (
    <StudyRowTable
      jobId="isolated-study"
      rows={[{ ...studyRow, label: 'Example A 原文', eligible: false }]}
      columns={studyColumns([studyContext], t)}
      hidden={hidden}
      active={false}
      onSource={vi.fn()}
    />
  );
}

describe('SAR source-identity column', () => {
  it.each(['en', 'zh-CN'] as const)('binds the header to its frozen row labels in %s', (locale) => {
    setLocale(locale);
    render(table());
    const heading = screen.getByRole('columnheader', {
      name: locale === 'en' ? 'Original ID' : '原文编号',
    });
    expect(heading).toHaveClass('sar-study-identifier');
    expect(heading).toHaveAttribute('scope', 'col');
    expect(screen.getByRole('rowheader', { name: 'Example A 原文' })).toBeVisible();
    expect(screen.getByRole('columnheader', { name: 'MW' })).not.toHaveClass(
      'sar-study-identifier',
    );
  });

  it('does not freeze another column when the source identifier is hidden', () => {
    const view = render(table(['label']));
    expect(screen.queryByRole('columnheader', { name: 'Original ID' })).not.toBeInTheDocument();
    expect(view.container.querySelector('.sar-study-identifier')).toBeNull();
    expect(screen.getByRole('columnheader', { name: 'Structure' })).not.toHaveClass(
      'sar-study-identifier',
    );
    view.rerender(table());
    expect(screen.getByRole('columnheader', { name: 'Original ID' })).toHaveClass(
      'sar-study-identifier',
    );
    expect(screen.getByRole('rowheader', { name: 'Example A 原文' })).toBeVisible();
  });
});
