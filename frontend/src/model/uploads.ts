export const maxPdfSize = 128 * 1024 * 1024;
export async function validatePdf(file: File): Promise<void> {
  if (!file.name.toLowerCase().endsWith('.pdf')) throw new Error('请选择 .pdf 格式文件。');
  if (!file.size) throw new Error('PDF 文件为空。');
  if (file.size > maxPdfSize) throw new Error('PDF 最大为 128 MiB。');
  if ((await file.slice(0, 5).text()) !== '%PDF-')
    throw new Error('文件头不是有效 PDF；服务端还会验证完整文档。');
}
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
