import React, { useState, useEffect, useCallback } from 'react';
import type { ManifestNode, ManifestData } from '../types';
import {
  collectCollapsedIds,
  collectDownloadableLeaves,
  toggleCheckRecursive,
  collectDeletableNodes,
} from '../utils/tree-helpers';
import { injectBookgetStyles } from '../styles/inject';

// ── Props ──

export interface ManifestTreeProps {
  /** The manifest data to display */
  manifest: ManifestData;
  /** Whether a download is currently active */
  isDownloading?: boolean;
  /** Called when user requests downloading selected nodes */
  onDownloadSelected?: (nodeIds: string[], concurrency: number) => void;
  /** Called when user requests downloading all nodes */
  onDownloadAll?: (concurrency: number) => void;
  /** Called when user requests expanding a node */
  onExpandNode?: (nodeId: string) => void;
  /** Called when user requests canceling download */
  onCancelDownload?: () => void;
  /** Called when user confirms deleting nodes */
  onDeleteNodes?: (nodeIds: string[]) => void;
}

// ── ManifestTree (combines toolbar + tree) ──

export const ManifestTree: React.FC<ManifestTreeProps> = ({
  manifest,
  isDownloading = false,
  onDownloadSelected,
  onDownloadAll,
  onExpandNode,
  onCancelDownload,
  onDeleteNodes,
}) => {
  injectBookgetStyles();
  const [checkedNodes, setCheckedNodes] = useState<Set<string>>(new Set());
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    collectCollapsedIds(manifest.structure, 0, 1, initial);
    return initial;
  });
  const [concurrency, setConcurrency] = useState(3);
  const [deleteMode, setDeleteMode] = useState(false);

  const p = manifest.progress ?? {
    total: 0, completed: 0, failed: 0, pending: 0, downloading: 0, percent: 0,
  };

  const toggleNodeCheck = useCallback((nodeId: string, node: ManifestNode) => {
    setCheckedNodes(prev => {
      const next = new Set(prev);
      const shouldCheck = !next.has(nodeId);
      toggleCheckRecursive(node, next, shouldCheck, deleteMode, collapsedNodes);
      return next;
    });
  }, [deleteMode, collapsedNodes]);

  const toggleCollapse = useCallback((nodeId: string) => {
    setCollapsedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const handleExpandNode = useCallback((nodeId: string) => {
    onExpandNode?.(nodeId);
  }, [onExpandNode]);

  const handleDownloadSelected = useCallback(() => {
    const leafIds = collectDownloadableLeaves(manifest.structure, checkedNodes);
    if (leafIds.length === 0) return;
    onDownloadSelected?.(leafIds, concurrency);
  }, [manifest.structure, checkedNodes, concurrency, onDownloadSelected]);

  const handleDownloadAll = useCallback(() => {
    onDownloadAll?.(concurrency);
  }, [concurrency, onDownloadAll]);

  const enterDeleteMode = useCallback(() => {
    setCheckedNodes(new Set());
    setDeleteMode(true);
  }, []);

  const cancelDeleteMode = useCallback(() => {
    setCheckedNodes(new Set());
    setDeleteMode(false);
  }, []);

  const confirmDelete = useCallback(() => {
    const nodeIds = collectDeletableNodes(manifest.structure, checkedNodes);
    if (nodeIds.length === 0) return;
    onDeleteNodes?.(nodeIds);
    setCheckedNodes(new Set());
    setDeleteMode(false);
  }, [manifest.structure, checkedNodes, onDeleteNodes]);

  const deleteCount = deleteMode
    ? collectDeletableNodes(manifest.structure, checkedNodes).length
    : 0;

  return (
    <div className="bdm-manifest-container" onClick={e => e.stopPropagation()}>
      {/* Toolbar */}
      <div className="bdm-manifest-toolbar">
        <span className="bdm-toolbar-progress">
          {p.completed}/{p.total} 已完成 ({p.percent}%)
          {p.failed > 0 && ` \u00B7 ${p.failed} 失败`}
        </span>
        <span className="bdm-toolbar-actions">
          {deleteMode ? (
            <>
              <span className="bdm-delete-hint">
                选择要删除的节点 {deleteCount > 0 && `(${deleteCount})`}
              </span>
              <button className="bdm-btn secondary" onClick={cancelDeleteMode}>取消</button>
              <button className="bdm-btn danger" onClick={confirmDelete} disabled={deleteCount === 0}>
                确认删除
              </button>
            </>
          ) : isDownloading ? (
            <>
              <span style={{ fontSize: 12, color: 'var(--bdm-warning)' }}>下载中...</span>
              <button className="bdm-btn danger" onClick={onCancelDownload}>停止下载</button>
            </>
          ) : (
            <>
              <label title="并行下载数量">
                并行:
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={concurrency}
                  onChange={e => {
                    const v = parseInt(e.target.value);
                    if (v >= 1 && v <= 50) setConcurrency(v);
                  }}
                />
              </label>
              <button className="bdm-btn secondary" onClick={handleDownloadSelected}>
                下载选中
              </button>
              <button className="bdm-btn" onClick={handleDownloadAll}>全部下载</button>
              <button className="bdm-btn danger" onClick={enterDeleteMode}>删除</button>
            </>
          )}
        </span>
      </div>

      {/* Tree */}
      <div className={`bdm-manifest-tree${deleteMode ? ' delete-mode' : ''}`}>
        <ManifestNodeView
          node={manifest.structure}
          depth={0}
          checkedNodes={checkedNodes}
          collapsedNodes={collapsedNodes}
          onToggleCheck={toggleNodeCheck}
          onToggleCollapse={toggleCollapse}
          onExpand={handleExpandNode}
          deleteMode={deleteMode}
        />
      </div>
    </div>
  );
};

// ── ManifestNodeView ──

interface ManifestNodeViewProps {
  node: ManifestNode;
  depth: number;
  checkedNodes: Set<string>;
  collapsedNodes: Set<string>;
  onToggleCheck: (nodeId: string, node: ManifestNode) => void;
  onToggleCollapse: (nodeId: string) => void;
  onExpand: (nodeId: string) => void;
  deleteMode?: boolean;
}

const ManifestNodeView: React.FC<ManifestNodeViewProps> = ({
  node, depth, checkedNodes, collapsedNodes,
  onToggleCheck, onToggleCollapse, onExpand, deleteMode,
}) => {
  const [loading, setLoading] = useState(false);
  const hasChildren = !!(node.children && node.children.length > 0);
  const isExpandable = !!node.expandable;
  const isRoot = node.type === 'root';
  const isCollapsed = collapsedNodes.has(node.id);

  const nodeIcon = node.type === 'root' ? '\u{1F4DA}' :
                   node.type === 'section' ? '\u{1F4C2}' :
                   node.type === 'volume' ? '\u{1F5BC}\uFE0F' : '\u{1F4C4}';

  const statusMap: Record<string, { label: string; cls: string }> = {
    completed: { label: '\u2713 已下载', cls: 'completed' },
    downloading: { label: '\u2193 下载中', cls: 'downloading' },
    discovered: { label: '\u25CB 待下载', cls: 'discovered' },
    pending: { label: '\u22EF 待展开', cls: 'pending' },
    failed: { label: '\u2717 失败', cls: 'failed' },
    skipped: { label: '- 跳过', cls: 'pending' },
  };
  const status = statusMap[node.status] || statusMap['pending'];

  let countInfo = '';
  if (node.text_count) countInfo += `${node.text_count}文`;
  if (node.image_count) countInfo += `${countInfo ? ' ' : ''}${node.image_count}图`;
  if (hasChildren && !countInfo) countInfo = `${node.children!.length}项`;

  const isCompleted = node.status === 'completed';
  const isDeletable = isCompleted || node.status === 'discovered';
  const isChecked = deleteMode
    ? checkedNodes.has(node.id)
    : (isCompleted || checkedNodes.has(node.id));
  const isDisabledCheck = deleteMode ? !isDeletable : isCompleted;

  const handleExpand = () => {
    if (hasChildren) {
      onToggleCollapse(node.id);
    } else if (isExpandable) {
      setLoading(true);
      onExpand(node.id);
    }
  };

  useEffect(() => {
    if (hasChildren && loading) setLoading(false);
  }, [hasChildren, loading]);

  return (
    <>
      <div className={`bdm-manifest-node ${loading ? 'loading' : ''}`}>
        <span className="bdm-node-indent" style={{ width: depth * 16 }} />
        {(hasChildren || isExpandable) ? (
          <span className="bdm-node-expand" onClick={handleExpand}>
            {loading ? '\u27F3' : hasChildren && !isCollapsed ? '\u25BC' : '\u25B6'}
          </span>
        ) : (
          <span className="bdm-node-expand empty">{' '}</span>
        )}
        {!isRoot && (
          <input
            type="checkbox"
            className="bdm-node-checkbox"
            checked={isChecked}
            disabled={isDisabledCheck}
            onChange={() => onToggleCheck(node.id, node)}
          />
        )}
        <span className="bdm-node-icon">{nodeIcon}</span>
        <span className="bdm-node-title" title={node.title}>{node.title}</span>
        {countInfo && <span className="bdm-node-count">{countInfo}</span>}
        <span className={`bdm-node-badge ${status.cls}`}>{status.label}</span>
      </div>
      {hasChildren && !isCollapsed && node.children!.map(child => (
        <ManifestNodeView
          key={child.id}
          node={child}
          depth={depth + 1}
          checkedNodes={checkedNodes}
          collapsedNodes={collapsedNodes}
          onToggleCheck={onToggleCheck}
          onToggleCollapse={onToggleCollapse}
          onExpand={onExpand}
          deleteMode={deleteMode}
        />
      ))}
    </>
  );
};
