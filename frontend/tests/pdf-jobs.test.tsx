import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { PageCanvas } from '../src/features/pdf/PageCanvas';
import { PageControls } from '../src/features/pdf/PageControls';
import { PdfPane } from '../src/features/pdf/PdfPane';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { JobActions } from '../src/features/jobs/JobActions';
import { Tabs } from '../src/components/Tabs';
import { job, page, project } from './fixtures';

describe('original PDF provenance and navigation', () => {
  it('distinguishes actual attached original images from historical OCR text without upgrading QA', async () => {
    const original = { ...page, source_mode: 'historical' as const };
    vi.spyOn(api, 'page').mockResolvedValue(original);
    const { rerender } = render(
      <PdfPane
        project={{ ...project, is_historical: true }}
        page={4}
        tab="annotations"
        selectedId="I-7"
        onPage={vi.fn()}
        onTab={vi.fn()}
        onSelect={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    expect(await screen.findByText('原始 PDF · 历史 OCR 待复核')).toBeVisible();
    expect(screen.queryByText(/非原始页面|原文未附/)).not.toBeInTheDocument();
    rerender(
      <PdfPane
        project={{ ...project, is_historical: true }}
        page={4}
        tab="text"
        selectedId="I-7"
        onPage={vi.fn()}
        onTab={vi.fn()}
        onSelect={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    expect(screen.getByText('历史 OCR 文本（非原生文本）')).toBeVisible();
  });
  it('shows actual scanned PNG even when no text source is available', () => {
    render(
      <PageCanvas
        page={{ ...page, source_mode: 'unavailable', text: '' }}
        zoom={1}
        annotations={false}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole('img')).toHaveAttribute(
      'src',
      '/api/v1/projects/project-contract/pages/4/image?scale=1',
    );
  });
  it('refuses synthetic original images for historical OCR pages', () => {
    render(
      <PageCanvas
        page={{ ...page, source_mode: 'historical', image_url: null }}
        zoom={1}
        annotations
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('原始 PDF 页面不可用')).toBeVisible();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
  it('uses real contract image paths and exact PDF-coordinate annotations', () => {
    const select = vi.fn();
    render(<PageCanvas page={page} zoom={1.5} annotations selectedId="I-7" onSelect={select} />);
    const image = screen.getByRole('img');
    expect(image).toHaveAttribute(
      'src',
      '/api/v1/projects/project-contract/pages/4/image?scale=1.5',
    );
    fireEvent.load(image);
    const overlay = screen.getByRole('button', { name: /定位化合物 I-7/ });
    expect(overlay).toHaveStyle({ left: '5%', top: `${(100 * 20) / 300}%`, width: '35%' });
    fireEvent.click(overlay);
    expect(select).toHaveBeenCalledWith('I-7');
  });
  it('renders OCR text as inert text, never as HTML', async () => {
    vi.spyOn(api, 'page').mockResolvedValue(page);
    render(
      <PdfPane
        project={project}
        page={4}
        tab="text"
        selectedId={null}
        onPage={vi.fn()}
        onTab={vi.fn()}
        onSelect={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    expect(await screen.findByText('<script>untrusted OCR</script>')).toBeVisible();
    expect(document.querySelector('script')).toBeNull();
  });
  it('uses an explicit unavailable-PDF state and offers attachment', async () => {
    const attach = vi.fn();
    render(
      <PdfPane
        project={{
          ...project,
          is_historical: true,
          pdf: { available: false, page_count: 0, sha256: null },
        }}
        page={1}
        tab="original"
        selectedId={null}
        onPage={vi.fn()}
        onTab={vi.fn()}
        onSelect={vi.fn()}
        onAttach={attach}
      />,
    );
    expect(screen.getByText('尚未提供原始 PDF')).toBeVisible();
    await userEvent.click(screen.getByText('补充原始 PDF'));
    expect(attach).toHaveBeenCalledOnce();
  });
  it('bounds page entry and zoom controls', () => {
    const onPage = vi.fn();
    const onZoom = vi.fn();
    render(
      <PageControls
        page={1}
        total={12}
        zoom={0.5}
        disabled={false}
        onPage={onPage}
        onZoom={onZoom}
      />,
    );
    expect(screen.getByLabelText('上一页原始文档')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '文档工具' }));
    expect(screen.getByLabelText('缩小原始文档')).toBeDisabled();
    const input = screen.getByLabelText('原始文档页码');
    fireEvent.change(input, { target: { value: '13' } });
    fireEvent.submit(input.closest('form')!);
    expect(onPage).not.toHaveBeenCalled();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    fireEvent.change(input, { target: { value: '12' } });
    fireEvent.submit(input.closest('form')!);
    expect(onPage).toHaveBeenCalledWith(12);
    fireEvent.click(screen.getByLabelText('放大原始文档'));
    expect(onZoom).toHaveBeenCalledWith(0.75);
  });
  it('supports arrow/Home/End tab focus without activating disabled capabilities', async () => {
    function TestTabs() {
      const [value, setValue] = useState('original');
      return (
        <Tabs
          label="视图"
          value={value}
          onChange={setValue}
          tabs={[
            { value: 'original', label: '原文' },
            { value: 'text', label: '文本' },
            { value: 'disabled', label: '未接入', disabled: true },
          ]}
        />
      );
    }
    render(<TestTabs />);
    const user = userEvent.setup();
    screen.getByRole('tab', { name: '原文' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: '文本' })).toHaveFocus();
    expect(screen.getByRole('tab', { name: '文本' })).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{Home}');
    expect(screen.getByRole('tab', { name: '原文' })).toHaveFocus();
  });
});
describe('core pipeline lifecycle presentation', () => {
  it('shows exactly the actual eight stages, not ADMET or guessed percentages', () => {
    render(<StageStrip job={job} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(8);
    expect(screen.getByText('文档分类')).toBeVisible();
    expect(screen.getByText('进行中')).toBeVisible();
    expect(screen.queryByText(/100%|ADMET/)).not.toBeInTheDocument();
  });
  it('starts only the existing core pipeline without paid advisory calls', async () => {
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    const onChange = vi.fn();
    render(<JobActions project={project} job={null} ready onChange={onChange} />);
    await userEvent.click(screen.getByText('运行提取'));
    await waitFor(() => expect(create).toHaveBeenCalledWith(project.id, null));
    expect(onChange).toHaveBeenCalledOnce();
  });
  it('cancel targets only the actual job and requires confirmation', async () => {
    const cancel = vi.spyOn(api, 'cancelJob').mockResolvedValue({ ...job, status: 'cancelled' });
    render(<JobActions project={project} job={job} ready onChange={vi.fn()} />);
    await userEvent.click(screen.getByText('取消任务'));
    expect(cancel).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('确认取消此任务'));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith(job.id));
  });
  it('resume passes the original job ID and respects runtime/PDF gates', async () => {
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    const { rerender } = render(
      <JobActions
        project={project}
        job={{ ...job, status: 'interrupted', can_resume: true }}
        ready={false}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText('继续提取')).toBeDisabled();
    rerender(
      <JobActions
        project={project}
        job={{ ...job, status: 'interrupted', can_resume: true }}
        ready
        onChange={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByText('继续提取'));
    await waitFor(() => expect(create).toHaveBeenCalledWith(project.id, job.id));
  });
});
