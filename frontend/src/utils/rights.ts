import type { RightsPrintGroup } from '../types'

export type DisplayRightsPrintGroup = RightsPrintGroup & { view_key?: string }

export function projectPrintGroups(
  groups: RightsPrintGroup[],
  mode: 'individual' | 'batch',
): DisplayRightsPrintGroup[] {
  if (mode === 'batch') return groups
  return groups.flatMap((group) => group.people.map((person, index) => ({
    ...group,
    group_label: `${person.name || group.group_label}（单独）`,
    people: [person],
    people_count: 1,
    view_key: `${group.task_number}:${group.group_id}:${person.row_number}:${index}`,
  })))
}
