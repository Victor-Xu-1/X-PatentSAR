import { describe, expect, it } from 'vitest';
import { acceptanceIssueCount, acceptanceIssueGroups } from '../src/model/acceptanceIssues';

describe('read-only bounded acceptance finding presentation', () => {
  it.each(['Compound 17A', 'Compound I-7', 'I-7', '28B', 'III-23'])(
    'keeps the explicit identifier %s intact',
    (subject) => {
      expect(acceptanceIssueGroups([`${subject}: First finding.`])).toEqual([
        { subject, issues: [{ message: 'First finding.', stages: [] }] },
      ]);
    },
  );
  it('retains reporting stages and all differing reasons without changing input order or content', () => {
    const raw = Object.freeze([
      'smiles: Compound 17A: First.',
      'final_export: Compound 17A: First.',
      'final_qa: Compound 17A: Second.',
      'qa: Count mismatch.',
      'Count mismatch.',
    ]);
    const groups = acceptanceIssueGroups(raw);
    expect(groups[0]).toEqual({
      subject: 'Compound 17A',
      issues: [
        { message: 'First.', stages: ['SMILES 识别', '生成结果'] },
        { message: 'Second.', stages: ['核心校验'] },
      ],
    });
    expect(groups[1]).toEqual({
      subject: null,
      issues: [{ message: 'Count mismatch.', stages: ['核心校验'] }],
    });
    expect(acceptanceIssueCount(groups)).toBe('1 条结构、1 项其他检查');
    expect(raw).toHaveLength(5);
  });
  it('keeps unfamiliar prefixes, category-like text and every malformed identifier as generic evidence', () => {
    const messages = [
      'transport: lost',
      '__proto__: untouched',
      'constructor: untouched',
      'RuntimeError: model failed',
      'Source graph mismatch.',
      'Compound : missing ID',
      'Other 12: not a proved identifier',
      'Compound 17A:',
    ];
    const groups = acceptanceIssueGroups(messages);
    expect(groups).toEqual([
      { subject: null, issues: messages.map((message) => ({ message, stages: [] })) },
    ]);
    expect(acceptanceIssueCount(groups)).toBe('8 项其他检查');
  });
  it('does not merge distinct suffixes, multiple subjects or contradictory observations', () => {
    const groups = acceptanceIssueGroups([
      'Compound 8A: Has defined stereo.',
      'Compound 8B: Has defined stereo.',
      'Compound 8A: Lacks defined stereo.',
      'smiles: Compound 8A and Compound 8B: shared finding.',
    ]);
    expect(groups.map((group) => group.subject)).toEqual(['Compound 8A', 'Compound 8B', null]);
    expect(groups[0]!.issues).toHaveLength(2);
    expect(groups[2]!.issues[0]!.message).toBe('Compound 8A and Compound 8B: shared finding.');
  });
  it('keeps empty findings empty rather than inventing a reason or successful acceptance', () => {
    expect(acceptanceIssueGroups([])).toEqual([]);
    expect(acceptanceIssueCount([])).toBe('');
  });
});
