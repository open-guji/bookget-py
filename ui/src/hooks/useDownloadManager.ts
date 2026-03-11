import { useState, useEffect, useCallback, useRef } from 'react';
import type { ManifestData, DownloadEvent } from '../types';
import type { TransportAdapter, DiscoverRequest, DownloadRequest, ExpandRequest, DeleteNodesRequest } from '../transport/types';

export interface DownloadManagerState {
  /** Manifest data keyed by taskId */
  manifests: Record<string, ManifestData>;
  /** Set of currently downloading taskIds */
  activeDownloads: Set<string>;
  /** Loading state for async operations */
  loading: boolean;
}

export interface DownloadManagerActions {
  discover: (req: DiscoverRequest) => Promise<ManifestData>;
  startDownload: (req: DownloadRequest) => Promise<void>;
  cancelDownload: (taskId: string) => Promise<void>;
  expandNode: (req: ExpandRequest) => Promise<ManifestData>;
  deleteNodes: (req: DeleteNodesRequest) => Promise<void>;
  /** Manually set/update a manifest (e.g. from external state) */
  setManifest: (taskId: string, manifest: ManifestData) => void;
}

/**
 * Core hook for managing download state via a TransportAdapter.
 */
export function useDownloadManager(
  transport: TransportAdapter,
): DownloadManagerState & DownloadManagerActions {
  const [manifests, setManifests] = useState<Record<string, ManifestData>>({});
  const [activeDownloads, setActiveDownloads] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const transportRef = useRef(transport);
  transportRef.current = transport;

  // Subscribe to transport events
  useEffect(() => {
    const unsub = transport.subscribe((event: DownloadEvent) => {
      switch (event.type) {
        case 'manifest_updated': {
          const manifest = event.data.manifest as ManifestData;
          if (manifest) {
            setManifests(prev => ({ ...prev, [event.taskId]: manifest }));
          }
          break;
        }
        case 'progress': {
          // Update active downloads set
          setActiveDownloads(prev => {
            if (!prev.has(event.taskId)) {
              const next = new Set(prev);
              next.add(event.taskId);
              return next;
            }
            return prev;
          });
          break;
        }
        case 'task_completed': {
          setActiveDownloads(prev => {
            const next = new Set(prev);
            next.delete(event.taskId);
            return next;
          });
          break;
        }
        case 'task_error': {
          setActiveDownloads(prev => {
            const next = new Set(prev);
            next.delete(event.taskId);
            return next;
          });
          break;
        }
      }
    });
    return unsub;
  }, [transport]);

  const discover = useCallback(async (req: DiscoverRequest): Promise<ManifestData> => {
    setLoading(true);
    try {
      const manifest = await transportRef.current.discover(req);
      return manifest;
    } finally {
      setLoading(false);
    }
  }, []);

  const startDownload = useCallback(async (req: DownloadRequest): Promise<void> => {
    setActiveDownloads(prev => new Set(prev).add(req.taskId));
    await transportRef.current.startDownload(req);
  }, []);

  const cancelDownload = useCallback(async (taskId: string): Promise<void> => {
    await transportRef.current.cancelDownload(taskId);
    setActiveDownloads(prev => {
      const next = new Set(prev);
      next.delete(taskId);
      return next;
    });
  }, []);

  const expandNode = useCallback(async (req: ExpandRequest): Promise<ManifestData> => {
    setLoading(true);
    try {
      const manifest = await transportRef.current.expandNode(req);
      setManifests(prev => ({ ...prev, [req.taskId]: manifest }));
      return manifest;
    } finally {
      setLoading(false);
    }
  }, []);

  const deleteNodes = useCallback(async (req: DeleteNodesRequest): Promise<void> => {
    await transportRef.current.deleteNodes(req);
  }, []);

  const setManifest = useCallback((taskId: string, manifest: ManifestData) => {
    setManifests(prev => ({ ...prev, [taskId]: manifest }));
  }, []);

  return {
    manifests,
    activeDownloads,
    loading,
    discover,
    startDownload,
    cancelDownload,
    expandNode,
    deleteNodes,
    setManifest,
  };
}
