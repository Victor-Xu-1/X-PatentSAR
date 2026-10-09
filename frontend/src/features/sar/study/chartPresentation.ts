import type { StudyBin } from '../../../api/sarStudyTypes';

const grades = ['#008c68', '#55b9a7', '#78a5c4', '#d8a142', '#ab80b7', '#d78270', '#c66475'];
const numeric = [
  '#087b60',
  '#299477',
  '#53ac91',
  '#80c3ab',
  '#add7c7',
  '#c6e1d7',
  '#dcece5',
  '#eaf2ee',
];
export type CountingUnit = 'molecules' | 'observations';
export function chartColor(bin: StudyBin, index: number, direction: 'lower' | 'higher' = 'lower') {
  if (['missing', 'unsupported', 'unresolved'].includes(bin.kind)) return '#a8b2ae';
  if (bin.kind === 'numeric')
    return numeric[direction === 'higher' ? 7 - Math.min(index, 7) : Math.min(index, 7)];
  if (bin.kind === 'interval') return '#997b4d';
  return grades[index % grades.length];
}
export function compactBinLabel(label: string) {
  const match = /^([[(])([^,]+),([^\])]+)([\])])$/.exec(label);
  if (!match) return label;
  const format = (raw: string) => {
    const value = Number(raw);
    if (!Number.isFinite(value) || (value === 0 && /[1-9]/.test(raw))) return raw;
    return new Intl.NumberFormat('en', {
      maximumSignificantDigits: 4,
      notation:
        Math.abs(value) >= 100000 || (value !== 0 && Math.abs(value) < 0.001)
          ? 'scientific'
          : 'standard',
    }).format(value);
  };
  return match[1] + format(match[2]!) + ', ' + format(match[3]!) + match[4];
}
export function composition(bins: StudyBin[], unit: CountingUnit) {
  const total = bins.reduce((sum, bin) => sum + bin[unit], 0);
  return {
    total,
    parts: bins.map((bin, index) => ({ bin, index, share: total ? bin[unit] / total : 0 })),
  };
}
