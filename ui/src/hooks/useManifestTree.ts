import { useState, useCallback } from 'react';
import type { ManifestNode, ManifestData } from '../types';
import { collectCollapsedIds } from '../utils/tree-helpers';

/**
 * Hook to manage manifest tree UI state (collapsed nodes, checked nodes).
 */
export function useManifestTree(manifest: ManifestData | undefined) {
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(() => {
    if (!manifest) return new Set();
    const initial = new Set<string>();
    collectCollapsedIds(manifest.structure, 0, 1, initial);
    return initial;
  });

  const [checkedNodes, setCheckedNodes] = useState<Set<string>>(new Set());

  const toggleCollapse = useCallback((nodeId: string) => {
    setCollapsedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const toggleCheck = useCallback((nodeId: string) => {
    setCheckedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const clearChecked = useCallback(() => {
    setCheckedNodes(new Set());
  }, []);

  return {
    collapsedNodes,
    checkedNodes,
    toggleCollapse,
    toggleCheck,
    clearChecked,
    setCollapsedNodes,
    setCheckedNodes,
  };
}
