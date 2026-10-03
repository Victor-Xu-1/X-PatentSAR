import { describe, expect, it } from 'vitest';
import { availableMetrics, recognitionText, redrawPlaceholder } from '../src/model/results';
import { activityValueText } from '../src/model/presentation';
import { compound } from './fixtures';

describe('result projection preserves measurements and independent state', () => {
  it('keeps catalog order and includes metrics absent from the server metric catalog', () => {
    expect(availableMetrics(['IC50', 'IC50'], [compound])).toEqual(['IC50', '抑制等级']);
    expect(availableMetrics([], [])).toEqual([]);
  });
  it('preserves units, zeros, censoring and unknown values in compact cells', () => {
    const activity = { ...compound.activities[0]!, value: '10 - 100 nM', unit: 'nM' };
    expect(activityValueText(activity)).toBe('10 - 100 nM');
    expect(activityValueText({ ...activity, value: 0 })).toBe('0 nM');
    expect(activityValueText({ ...activity, value: '<1' })).toBe('<1 nM');
    expect(activityValueText({ ...activity, value: null })).toBe('值未提供');
  });
  it('does not infer recognition from binding or SMILES and keeps parseability modest', () => {
    expect(recognitionText(null)).toBe('识别状态未知');
    expect(
      recognitionText({
        status: 'valid',
        quality_flag: 'needs_qc',
        model_fingerprint: null,
        token_confidence: null,
      }),
    ).toBe('RDKit 可解析');
  });
  it('distinguishes no-SMILES, invalid-SMILES and unknown redraw generation', () => {
    expect(redrawPlaceholder(compound)).toBe('未提供 SMILES，无法重绘');
    expect(
      redrawPlaceholder({
        ...compound,
        smiles: 'bad',
        recognition: {
          status: 'invalid',
          quality_flag: 'invalid',
          model_fingerprint: null,
          token_confidence: null,
        },
      }),
    ).toBe('SMILES 未通过 RDKit 校验，无法重绘');
    expect(redrawPlaceholder({ ...compound, smiles: 'CCO' })).toBe(
      '重绘图片未提供（生成状态未知）',
    );
  });
});
