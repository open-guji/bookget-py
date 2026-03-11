/**
 * Format byte size to human-readable string.
 */
export function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * Get a file icon based on extension.
 */
export function getFileIcon(extension: string | null): string {
  if (!extension) return '\u{1F4C4}';
  const ext = extension.toLowerCase();
  if (['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'].includes(ext)) return '\u{1F5BC}\uFE0F';
  if (['.pdf'].includes(ext)) return '\u{1F4D5}';
  if (['.txt', '.md'].includes(ext)) return '\u{1F4DD}';
  if (['.doc', '.docx'].includes(ext)) return '\u{1F4D8}';
  if (['.xls', '.xlsx'].includes(ext)) return '\u{1F4CA}';
  if (['.zip', '.rar', '.7z'].includes(ext)) return '\u{1F4E6}';
  return '\u{1F4C4}';
}
