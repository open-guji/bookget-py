import React, { useState, useCallback } from 'react';
import type { ManifestData, SiteInfo } from '../types';
import type { TransportAdapter } from '../transport/types';
import { useDownloadManager } from '../hooks/useDownloadManager';
import { ManifestTree } from './ManifestTree';
import { TaskList } from './TaskList';
import type { TaskCardProps } from './TaskCard';

export interface DownloadDashboardProps {
  /** The transport adapter for backend communication */
  transport: TransportAdapter;
  /** Default output directory (optional) */
  defaultOutputDir?: string;
  /** External task items for the TaskList (optional, e.g. from VS Code extension) */
  externalTasks?: TaskCardProps[];
  /** Whether to show the URL input form (default: true) */
  showUrlInput?: boolean;
  /** Callback when cancel is requested */
  onCancelTask?: (taskId: string) => void;
}

/**
 * Top-level dashboard component combining URL input, manifest tree, and task list.
 * Use this as the main entry point for the download management UI.
 */
export const DownloadDashboard: React.FC<DownloadDashboardProps> = ({
  transport,
  defaultOutputDir = './downloads',
  externalTasks,
  showUrlInput = true,
  onCancelTask,
}) => {
  const {
    manifests, activeDownloads, loading,
    discover, startDownload, cancelDownload, expandNode, deleteNodes, setManifest,
  } = useDownloadManager(transport);

  const [url, setUrl] = useState('');
  const [outputDir, setOutputDir] = useState(defaultOutputDir);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [siteInfo, setSiteInfo] = useState<SiteInfo | null>(null);

  const handleDiscover = useCallback(async () => {
    if (!url.trim()) return;
    setError(null);

    try {
      // Check URL support
      const check = await transport.checkUrl(url);
      if (!check.supported) {
        setError('不支持此网址');
        return;
      }
      setSiteInfo(check.site ?? null);

      // Discover structure
      const manifest = await discover({ url, outputDir, depth: 1 });
      const taskId = manifest.book_id || url;
      setManifest(taskId, manifest);
      setCurrentTaskId(taskId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [url, outputDir, transport, discover, setManifest]);

  const currentManifest = currentTaskId ? manifests[currentTaskId] : null;
  const isCurrentDownloading = currentTaskId ? activeDownloads.has(currentTaskId) : false;

  const handleDownloadSelected = useCallback((nodeIds: string[], concurrency: number) => {
    if (!currentTaskId) return;
    startDownload({
      taskId: currentTaskId,
      url,
      outputDir,
      nodeIds,
      concurrency,
    });
  }, [currentTaskId, url, outputDir, startDownload]);

  const handleDownloadAll = useCallback((concurrency: number) => {
    if (!currentTaskId) return;
    startDownload({
      taskId: currentTaskId,
      url,
      outputDir,
      concurrency,
    });
  }, [currentTaskId, url, outputDir, startDownload]);

  const handleExpandNode = useCallback((nodeId: string) => {
    if (!currentTaskId) return;
    expandNode({
      taskId: currentTaskId,
      url,
      outputDir,
      nodeId,
    });
  }, [currentTaskId, url, outputDir, expandNode]);

  const handleCancelDownload = useCallback(() => {
    if (!currentTaskId) return;
    cancelDownload(currentTaskId);
    onCancelTask?.(currentTaskId);
  }, [currentTaskId, cancelDownload, onCancelTask]);

  const handleDeleteNodes = useCallback((nodeIds: string[]) => {
    if (!currentTaskId) return;
    deleteNodes({ taskId: currentTaskId, nodeIds });
  }, [currentTaskId, deleteNodes]);

  // Build task list from active downloads
  const tasks: TaskCardProps[] = externalTasks ?? Object.entries(manifests)
    .filter(([id]) => activeDownloads.has(id))
    .map(([id, m]) => ({
      id,
      name: m.title || id,
      progress: m.progress?.percent ?? 0,
      status: 'downloading' as const,
      message: `${m.progress?.completed ?? 0}/${m.progress?.total ?? 0}`,
    }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: 8 }}>
      {/* URL Input */}
      {showUrlInput && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="text"
              value={url}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleDiscover(); }}
              placeholder="输入古籍网址..."
              style={{
                flex: 1,
                padding: '6px 10px',
                background: 'var(--bdm-bg)',
                color: 'var(--bdm-text)',
                border: '1px solid var(--bdm-card-border)',
                borderRadius: 'var(--bdm-border-radius)',
                fontSize: 'var(--bdm-font-size)',
                fontFamily: 'var(--bdm-font-family)',
              }}
            />
            <button className="bdm-btn" onClick={handleDiscover} disabled={loading || !url.trim()}>
              {loading ? '发现中...' : '发现结构'}
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 'var(--bdm-font-size-sm)', color: 'var(--bdm-text-dim)' }}>
              输出目录:
            </label>
            <input
              type="text"
              value={outputDir}
              onChange={e => setOutputDir(e.target.value)}
              style={{
                flex: 1,
                padding: '4px 8px',
                background: 'var(--bdm-bg)',
                color: 'var(--bdm-text)',
                border: '1px solid var(--bdm-card-border)',
                borderRadius: 'var(--bdm-border-radius)',
                fontSize: 'var(--bdm-font-size-sm)',
                fontFamily: 'var(--bdm-font-family)',
              }}
            />
          </div>

          {siteInfo && (
            <div style={{ fontSize: 'var(--bdm-font-size-sm)', color: 'var(--bdm-text-dim)' }}>
              来源: {siteInfo.site_name}
              {siteInfo.supports_text && ' · 文字'}
              {siteInfo.supports_images && ' · 图片'}
            </div>
          )}

          {error && (
            <div style={{ fontSize: 'var(--bdm-font-size-sm)', color: 'var(--bdm-error)' }}>
              {error}
            </div>
          )}
        </div>
      )}

      {/* Manifest Tree */}
      {currentManifest && (
        <ManifestTree
          manifest={currentManifest}
          isDownloading={isCurrentDownloading}
          onDownloadSelected={handleDownloadSelected}
          onDownloadAll={handleDownloadAll}
          onExpandNode={handleExpandNode}
          onCancelDownload={handleCancelDownload}
          onDeleteNodes={handleDeleteNodes}
        />
      )}

      {/* Task List */}
      {tasks.length > 0 && (
        <TaskList
          tasks={tasks}
          onCancel={onCancelTask ?? cancelDownload}
        />
      )}
    </div>
  );
};
