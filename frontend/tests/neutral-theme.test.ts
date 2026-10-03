import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = (name: string) =>
  readFileSync(new URL('../src/styles/' + name, import.meta.url), 'utf8');
const tokens = css('tokens.css');
const token = (name: string) => tokens.match(new RegExp('--' + name + ':\\s*([^;]+);'))?.[1];

describe('one neutral system-font design authority', () => {
  it('uses white and gray surfaces with an almost-black monochrome primary', () => {
    expect(token('canvas')).toBe('#ffffff');
    expect(token('surface')).toBe('#ffffff');
    expect(token('surface-subtle')).toBe('#f7f7f8');
    expect(token('primary')).toBe('#212121');
    expect(token('accent')).toBe('#212121');
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
});
