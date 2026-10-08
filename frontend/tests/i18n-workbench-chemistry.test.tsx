import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { CorrectionDocument } from '../src/api/correctionTypes';
import { setLocale, UiError } from '../src/i18n';
import { CorrectionDialog } from '../src/features/results/CorrectionDialog';
import { CropDialog } from '../src/features/results/CropDialog';
import StructureEditor from '../src/features/results/StructureEditor';
import { EDITOR_CHANNEL, readEditorMessage } from '../src/features/structure-editor/protocol';
import { descriptorSummary } from './descriptor-fixtures';
import { project } from './fixtures';
import {
  activity,
  row,
  frameMessage,
  setupWorkbenchLocale,
  switchTo,
} from './i18n-workbench-fixtures';

setupWorkbenchLocale();

describe('workbench interface language and data boundaries', () => {
  it('keeps correction and drawing instances, drafts and saved error descriptors on switch-back', async () => {
    setLocale('zh-CN');
    const fields = { display_id: row.display_id, smiles: row.smiles, activities: row.activities };
    const correction: CorrectionDocument = {
      source_fingerprint: 'b'.repeat(64),
      basis_fingerprint: null,
      revision: 0,
      stale: false,
      has_changes: false,
      original: fields,
      values: fields,
      updated_at: null,
    };
    const get = vi.spyOn(api, 'getCorrection').mockResolvedValue(correction);
    const save = vi.spyOn(api, 'saveCorrection').mockRejectedValue(new UiError('修正保存失败。'));
    const onSaved = vi.fn();
    render(
      <CorrectionDialog
        projectId={project.id}
        compound={row}
        activityColumns={[activity]}
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );
    const id = await screen.findByRole('textbox', { name: '修正化合物编号' });
    const frame = screen.getByTitle('Ketcher 结构绘制与预览');
    fireEvent.change(id, { target: { value: '用户编号 7A' } });
    const metric = screen.getByRole('textbox', { name: '修正 LogP' });
    fireEvent.change(metric, { target: { value: 'NaN' } });
    act(() =>
      window.dispatchEvent(
        new MessageEvent('message', {
          origin: window.location.origin,
          source: (frame as HTMLIFrameElement).contentWindow,
          data: { channel: EDITOR_CHANNEL, kind: 'loaded' },
        }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: '保存修正' }));
    await screen.findByText('LogP 必须是有限数字，或留空。');
    expect(save).not.toHaveBeenCalled();
    switchTo('en');
    expect(screen.getByText('LogP must be a finite number or blank.')).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Correct LogP' })).toBe(metric);
    expect(metric).toHaveValue('NaN');
    expect(screen.getByTitle('Ketcher structure drawing and preview')).toBe(frame);
    switchTo('zh-CN');
    fireEvent.change(metric, { target: { value: '-1.25' } });
    fireEvent.click(screen.getByRole('button', { name: '保存修正' }));
    await screen.findByText('修正保存失败。');
    switchTo('en');
    expect(screen.getByRole('textbox', { name: 'Correct compound ID' })).toBe(id);
    expect(id).toHaveValue('用户编号 7A');
    expect(screen.getByRole('textbox', { name: 'Correct LogP' })).toBe(metric);
    expect(metric).toHaveValue('-1.25');
    expect(screen.getByTitle('Ketcher structure drawing and preview')).toBe(frame);
    expect(screen.getByText('Could not save the correction.')).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByTitle('Ketcher 结构绘制与预览')).toBe(frame);
    expect(screen.getByText('修正保存失败。')).toBeVisible();
    await waitFor(() => expect(get).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledOnce();
    expect(onSaved).not.toHaveBeenCalled();
  });
});

describe('English workbench view and live language continuity', () => {
  it('presents recognition and independent descriptors in English while retaining their original observations', () => {
    render(
      <CropDialog
        projectId={project.id}
        compound={{
          ...row,
          confidence: { ...row.confidence, reason: '原始绑定诊断' },
          descriptors: descriptorSummary,
          recognition: {
            status: 'valid',
            quality_flag: null,
            model_fingerprint: 'raw-model-id',
            token_confidence: { minimum: 0.4, mean: 0.8 },
          },
        }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('Five calculations · Calculated; LogS · Not calculated')).toBeVisible();
    fireEvent.click(screen.getByText('Original extraction evidence / validation'));
    expect(screen.getByText('RDKit parsable')).toBeVisible();
    expect(screen.getByText('raw-model-id')).toBeVisible();
    expect(screen.getByText(/原始绑定诊断/)).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByText('RDKit 可解析')).toBeVisible();
    switchTo('en');
    expect(screen.getByText('raw-model-id')).toBeVisible();
  });
  it('relocalizes frame-owned errors but preserves raw diagnostics and never reloads or captures the drawing on locale changes', () => {
    const ready = vi.fn(),
      change = vi.fn(),
      save = vi.fn();
    render(
      <StructureEditor
        smiles={row.smiles}
        molfile={null}
        disabled={false}
        onReady={ready}
        onChange={change}
        onSave={save}
      />,
    );
    const frame = screen.getByTitle('Ketcher structure drawing and preview') as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow!, 'postMessage');
    frameMessage(frame, { kind: 'loaded' });
    const source = '绘图操作失败，请重新加载编辑器。';
    frameMessage(frame, { kind: 'error', message: source, source, recoverable: true });
    expect(screen.getByText('The drawing operation failed. Reload the editor.')).toBeVisible();
    const callbacks = ready.mock.calls.length;
    switchTo('zh-CN');
    expect(screen.getByText(source)).toBeVisible();
    switchTo('en');
    expect(screen.getByTitle('Ketcher structure drawing and preview')).toBe(frame);
    expect(ready).toHaveBeenCalledTimes(callbacks);
    expect(post).not.toHaveBeenCalled();
    frameMessage(frame, { kind: 'error', message: source, recoverable: true });
    expect(screen.getByText(source)).toBeVisible();
    switchTo('zh-CN');
    switchTo('en');
    expect(screen.getByText(source)).toBeVisible();
    expect(change).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
    expect(() =>
      readEditorMessage({
        channel: EDITOR_CHANNEL,
        kind: 'error',
        message: 'raw',
        source: 'x'.repeat(1001),
        recoverable: false,
      }),
    ).toThrow(UiError);
  });
});
