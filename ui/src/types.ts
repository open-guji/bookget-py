// Shared types for bookget-ui — mirrors bookget-py manifest.json structure

/** Node type in the manifest tree */
export type NodeType = 'root' | 'section' | 'volume' | 'chapter';

/** Node download status */
export type NodeStatus = 'pending' | 'discovered' | 'downloading' | 'completed' | 'failed' | 'skipped';

/** Resource kind */
export type ResourceKind = 'text' | 'image' | 'mixed';

/** A node in the manifest tree */
export interface ManifestNode {
  id: string;
  title: string;
  type: NodeType;
  status: NodeStatus;
  resource_kind?: ResourceKind;
  text_count?: number;
  image_count?: number;
  children?: ManifestNode[];
  children_count?: number;
  expandable?: boolean;
  downloaded_items?: number;
  total_items?: number;
  failed_items?: number;
  source_data?: Record<string, unknown>;
  local_path?: string;
}

/** Progress statistics */
export interface ManifestProgress {
  total: number;
  completed: number;
  failed: number;
  pending: number;
  downloading: number;
  percent: number;
}

/** Full manifest data */
export interface ManifestData {
  version: number;
  book_id: string;
  source_url: string;
  source_site: string;
  title: string;
  metadata: Record<string, unknown>;
  structure: ManifestNode;
  discovery_complete: boolean;
  progress: ManifestProgress;
  created_at: string;
  updated_at: string;
}

/** Site information */
export interface SiteInfo {
  site_id: string;
  site_name: string;
  site_domains: string[];
  supports_text: boolean;
  supports_images: boolean;
}

/** Download event pushed from backend */
export type DownloadEventType =
  | 'progress'
  | 'manifest_updated'
  | 'task_completed'
  | 'task_error'
  | 'log';

export interface DownloadEvent {
  type: DownloadEventType;
  taskId: string;
  data: Record<string, unknown>;
}
