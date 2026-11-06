import type {KnowledgeDocument} from './model';

export const temporaryImportLimits = {fileBytes: 1024 * 1024, totalBytes: 5 * 1024 * 1024, count: 10};
export type TemporaryDocument = Extract<KnowledgeDocument, {kind: 'temporary'}>;

export async function readTemporaryDocument(file: File): Promise<TemporaryDocument> {
  if (!/\.(txt|md|csv)$/i.test(file.name)) throw new Error('目前支持 TXT、Markdown（.md）和 CSV，请选择这些格式的文本文件。');
  if (file.size === 0) throw new Error('文件是空的，请选择包含文字的文件。');
  if (file.size > temporaryImportLimits.fileBytes) throw new Error('单个文件不能超过 1 MB，请精简后重试。');
  let buffer: ArrayBuffer;
  try { buffer = await file.arrayBuffer(); }
  catch { throw new Error('文件读取失败，请重新选择文件。'); }
  const bytes = new Uint8Array(buffer);
  if (bytes.length > temporaryImportLimits.fileBytes) throw new Error('单个文件不能超过 1 MB，请精简后重试。');
  // Reject common binary formats even when the extension has been changed.
  const signature = String.fromCharCode(...bytes.slice(0, 8));
  if (/^(%PDF-|PK\x03\x04|\x89PNG|\xff\xd8\xff|GIF8[79]a|\xd0\xcf\x11\xe0)/.test(signature)) {
    throw new Error('文件内容不是支持的文本，请勿直接修改 PDF、图片或 Office 文件的后缀。');
  }
  const encoding = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le'
    : bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : 'utf-8';
  let text: string;
  try { text = new TextDecoder(encoding, {fatal: true}).decode(bytes); }
  catch { throw new Error('无法读取文字编码，请将文件另存为 UTF-8 后重新导入。'); }
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text)) {
    throw new Error('文件含有二进制或无效控制字符，请选择纯文本文件。');
  }
  if (!text.trim()) throw new Error('文件没有可检索的文字，请检查内容后重试。');
  const fingerprint = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer)), byte => byte.toString(16).padStart(2, '0')).join('');
  return {id: 'temporary-' + crypto.randomUUID(), kind: 'temporary', title: file.name,
    text, source: '临时导入 · 仅当前页面', original: file, fingerprint};
}

export function addTemporaryDocument(current: TemporaryDocument[], doc: TemporaryDocument): TemporaryDocument[] {
  if (current.some(item => item.title === doc.title && item.fingerprint === doc.fingerprint)) throw new Error('这份同名、同内容的文件已导入，无需重复添加。');
  if (current.length >= temporaryImportLimits.count) throw new Error('最多临时导入 10 份资料，请先移除不需要的资料。');
  if (current.reduce((sum, item) => sum + item.original.size, doc.original.size) > temporaryImportLimits.totalBytes) {
    throw new Error('临时资料合计不能超过 5 MB，请先移除不需要的资料。');
  }
  return [doc, ...current];
}
