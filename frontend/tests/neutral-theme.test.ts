import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = (name: string) =>
  readFileSync(new URL('../src/styles/' + name, import.meta.url), 'utf8');
const tokens = css('tokens.css');
const token = (name: string) => tokens.match(new RegExp('--' + name + ':\\s*([^;]+);'))?.[1];
function luminance(value: string) {
  const channels = value.match(/[\da-f]{2}/gi)!.map((hex) => {
    const channel = Number.parseInt(hex, 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
}
function contrast(foreground: string, background: string) {
  const values = [luminance(token(foreground)!), luminance(token(background)!)].sort(
    (a, b) => b - a,
  );
  return (values[0]! + 0.05) / (values[1]! + 0.05);
}

describe('one restrained biomedical system-font design authority', () => {
  it('keeps small metadata and scientific values readable on their actual surfaces', () => {
    for (const background of ['surface', 'surface-subtle', 'canvas']) {
      for (const foreground of ['ink', 'primary', 'muted', 'faint'])
        expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast('primary', 'activity-strong-surface')).toBeGreaterThanOrEqual(4.5);
    expect(contrast('primary', 'activity-medium-surface')).toBeGreaterThanOrEqual(4.5);
  });
  it('uses cool-neutral surfaces, charcoal actions and limited biomedical accents', () => {
    expect(token('canvas')).toBe('#f5f7f7');
    expect(token('surface')).toBe('#ffffff');
    expect(token('surface-subtle')).toBe('#f6f8f8');
    expect(token('primary')).toBe('#202a2f');
    expect(token('accent')).toBe('#17735d');
    expect(token('success-surface')).toBe('#ecf8f1');
    expect(token('on-primary')).toBe('#ffffff');
  });

  it('uses the same system sans-serif family for headings and interface text', () => {
    expect(token('font-ui')).toContain('system-ui');
    expect(token('font-heading')).toBe('var(--font-ui)');
    expect(tokens).not.toMatch(/Georgia|Times New Roman|Noto Serif|Songti|#c96442|#a34c30/i);
  });

  it('preserves keyboard focus and reduced-motion support while avoiding remote font assets', () => {
    expect(css('base.css')).toContain(':focus-visible');
    expect(css('base.css')).toContain('@media (prefers-reduced-motion: reduce)');
    expect(tokens).not.toMatch(/@import|url\(/i);
  });

  it('does not revive the retired navigation or project-card design', () => {
    expect(tokens).not.toContain('--sidebar-width');
    expect(css('management.css')).not.toMatch(/\.eyebrow|\.project-(grid|card|icon)/);
  });

  it('keeps real PDF and table surfaces white, with unframed source structures', () => {
    expect(token('image-paper')).toBe('#ffffff');
    expect(css('table.css')).toMatch(/\.crop-button\s*\{[^}]*border: 0;/);
    expect(css('table.css')).toMatch(/\.crop-button img\s*\{[^}]*object-fit: contain;/);
    expect(css('pdf.css')).toMatch(/\.pdf-content\s*\{[^}]*background: var\(--surface-subtle\);/);
    expect(css('shell.css')).not.toMatch(/\.recent-file\s*\{/);
  });
});
