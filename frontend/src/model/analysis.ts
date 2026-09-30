export function parseSmiles(input: string): string[] {
  const molecules = input
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!molecules.length) throw new Error('请输入至少一个 SMILES，或先识别真实结构裁图。');
  if (molecules.length > 50) throw new Error('每批最多 50 个分子，请分批分析。');
  if (molecules.some((smiles) => /\s/.test(smiles)))
    throw new Error('每行只能包含一个 SMILES，不允许内部空白或分子名称。');
  if (molecules.some((smiles) => smiles.length > 4096))
    throw new Error('单个 SMILES 超过前端 4096 字符安全限制。');
  return molecules;
}
