// bookget-ui — React components for managing ancient book downloads
// https://github.com/xxx/bookget-py

// Types
export type {
  NodeType,
  NodeStatus,
  ResourceKind,
  ManifestNode,
  ManifestProgress,
  ManifestData,
  SiteInfo,
  DownloadEventType,
  DownloadEvent,
} from './types';

// Transport
export type {
  TransportAdapter,
  DiscoverRequest,
  DownloadRequest,
  ExpandRequest,
  DeleteNodesRequest,
} from './transport/types';
export { HttpTransport } from './transport/http-transport';
export { VscodeTransport } from './transport/vscode-transport';

// Components
export { ManifestTree } from './components/ManifestTree';
export type { ManifestTreeProps } from './components/ManifestTree';
export { TaskList } from './components/TaskList';
export type { TaskListProps } from './components/TaskList';
export { TaskCard } from './components/TaskCard';
export type { TaskCardProps } from './components/TaskCard';
export { ProgressBar } from './components/ProgressBar';
export type { ProgressBarProps } from './components/ProgressBar';
export { DownloadDashboard } from './components/DownloadDashboard';
export type { DownloadDashboardProps } from './components/DownloadDashboard';

// Hooks
export { useDownloadManager } from './hooks/useDownloadManager';
export { useManifestTree } from './hooks/useManifestTree';

// Utilities
export {
  collectCollapsedIds,
  collectDownloadableLeaves,
  toggleCheckRecursive,
  collectDeletableNodes,
} from './utils/tree-helpers';
export { formatSize, getFileIcon } from './utils/format';

// Styles — import 'bookget-ui/styles' to include default theme
import './styles/components.css';
