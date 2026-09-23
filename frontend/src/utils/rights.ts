export function estimateRightsOutputCount(
  printGroupCount: number,
  recordCount: number,
  mode: 'individual' | 'batch',
): number {
  return mode === 'individual' ? recordCount : printGroupCount
}
