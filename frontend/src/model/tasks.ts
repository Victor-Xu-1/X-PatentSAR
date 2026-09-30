export function normalizePatentId(value: string): string {
  const normalized = value.trim().toUpperCase();
  if (!normalized) return '';
  const id = normalized.startsWith('WO') ? normalized.replaceAll('/', '') : normalized;
  if (!/^[A-Z][A-Z0-9._-]{0,63}$/.test(id))
    throw new Error(
      '专利标识须为最多 64 个字符的 ASCII 标识，以字母开头；仅 WO 可包含 / 并自动归一化，不能输入路径或命令。',
    );
  return id;
}
