import type { ManifestData, SiteInfo, DownloadEvent } from '../types';

/** Request to discover book structure */
export interface DiscoverRequest {
  url: string;
  outputDir?: string;
  depth?: number;
}

/** Request to start downloading */
export interface DownloadRequest {
  taskId: string;
  url: string;
  outputDir: string;
  nodeIds?: string[];
  concurrency?: number;
}

/** Request to expand a manifest node */
export interface ExpandRequest {
  taskId: string;
  url: string;
  outputDir: string;
  nodeId: string;
}

/** Request to delete downloaded nodes */
export interface DeleteNodesRequest {
  taskId: string;
  nodeIds: string[];
}

/**
 * Transport adapter interface — abstracts communication between UI and backend.
 *
 * Implementations:
 * - HttpTransport: REST + SSE for standalone web mode
 * - VscodeTransport: postMessage for VS Code webview mode
 */
export interface TransportAdapter {
  // Commands
  discover(req: DiscoverRequest): Promise<ManifestData>;
  startDownload(req: DownloadRequest): Promise<void>;
  cancelDownload(taskId: string): Promise<void>;
  expandNode(req: ExpandRequest): Promise<ManifestData>;
  deleteNodes(req: DeleteNodesRequest): Promise<void>;

  // Queries
  getSupportedSites(): Promise<SiteInfo[]>;
  checkUrl(url: string): Promise<{ supported: boolean; site?: SiteInfo }>;

  // Event subscription — returns unsubscribe function
  subscribe(listener: (event: DownloadEvent) => void): () => void;

  // Lifecycle
  dispose(): void;
}
