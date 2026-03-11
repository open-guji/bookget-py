import type { ManifestNode } from '../types';

/**
 * Collect IDs of nodes at depth >= maxDepth that have children (should be collapsed).
 */
export function collectCollapsedIds(
  node: ManifestNode,
  depth: number,
  maxDepth: number,
  result: Set<string>,
): void {
  if (!node.children?.length) return;
  if (depth >= maxDepth) {
    result.add(node.id);
  }
  for (const child of node.children) {
    collectCollapsedIds(child, depth + 1, maxDepth, result);
  }
}

/**
 * Collect IDs of checked nodes for download.
 * If a parent node is checked, pass its ID directly (bookget handles child filtering).
 * Only recurse into unchecked parents to find checked descendants.
 */
export function collectDownloadableLeaves(
  node: ManifestNode,
  checked: Set<string>,
): string[] {
  const notDownloadable = new Set(['completed']);
  const result: string[] = [];

  function walk(n: ManifestNode) {
    if (checked.has(n.id) && !notDownloadable.has(n.status)) {
      result.push(n.id);
      return;
    }
    if (n.children?.length) {
      for (const child of n.children) walk(child);
    }
  }

  walk(node);
  return result;
}

/**
 * Toggle check state recursively for a node and its visible children.
 */
export function toggleCheckRecursive(
  node: ManifestNode,
  checked: Set<string>,
  shouldCheck: boolean,
  deleteMode?: boolean,
  collapsedNodes?: Set<string>,
): void {
  const canToggle = deleteMode
    ? node.status === 'completed' || node.status === 'discovered'
    : node.status !== 'completed';

  if (canToggle) {
    if (shouldCheck) checked.add(node.id);
    else checked.delete(node.id);
  }

  // Only recurse into expanded (not collapsed) children
  if (node.children && !(collapsedNodes && collapsedNodes.has(node.id))) {
    for (const child of node.children) {
      toggleCheckRecursive(child, checked, shouldCheck, deleteMode, collapsedNodes);
    }
  }
}

/**
 * Collect the highest-level checked deletable node IDs.
 * If a parent is checked, its children are not included (the parent covers them).
 */
export function collectDeletableNodes(
  node: ManifestNode,
  checked: Set<string>,
): string[] {
  const result: string[] = [];

  function walk(n: ManifestNode) {
    if (
      n.type !== 'root' &&
      checked.has(n.id) &&
      (n.status === 'completed' || n.status === 'discovered')
    ) {
      result.push(n.id);
      return;
    }
    if (n.children) {
      for (const child of n.children) walk(child);
    }
  }

  walk(node);
  return result;
}
