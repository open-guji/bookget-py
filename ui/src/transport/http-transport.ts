import type { ManifestData, SiteInfo, DownloadEvent } from '../types';
import type {
  TransportAdapter,
  DiscoverRequest,
  DownloadRequest,
  ExpandRequest,
  DeleteNodesRequest,
} from './types';

/**
 * HTTP Transport — communicates with bookget server via REST + SSE.
 * Used in standalone web mode.
 */
export class HttpTransport implements TransportAdapter {
  private baseUrl: string;
  private eventSource: EventSource | null = null;
  private listeners = new Set<(event: DownloadEvent) => void>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(baseUrl: string = '') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.connectSSE();
  }

  private connectSSE() {
    if (this.eventSource) {
      this.eventSource.close();
    }

    this.eventSource = new EventSource(`${this.baseUrl}/api/events`);

    const eventTypes = ['progress', 'manifest_updated', 'task_completed', 'task_error', 'log'] as const;
    for (const type of eventTypes) {
      this.eventSource.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          const event: DownloadEvent = {
            type,
            taskId: data.taskId ?? '',
            data,
          };
          this.emit(event);
        } catch {
          // ignore parse errors
        }
      });
    }

    this.eventSource.onerror = () => {
      this.eventSource?.close();
      this.eventSource = null;
      // Reconnect after 3 seconds
      this.reconnectTimer = setTimeout(() => this.connectSSE(), 3000);
    };
  }

  private emit(event: DownloadEvent) {
    for (const listener of this.listeners) {
      listener(event);
    }
  }

  private async fetch<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    return res.json();
  }

  async discover(req: DiscoverRequest): Promise<ManifestData> {
    return this.fetch('/api/discover', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async startDownload(req: DownloadRequest): Promise<void> {
    await this.fetch('/api/download', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async cancelDownload(taskId: string): Promise<void> {
    await this.fetch(`/api/download/${encodeURIComponent(taskId)}`, {
      method: 'DELETE',
    });
  }

  async expandNode(req: ExpandRequest): Promise<ManifestData> {
    return this.fetch('/api/expand', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  async deleteNodes(req: DeleteNodesRequest): Promise<void> {
    await this.fetch('/api/nodes', {
      method: 'DELETE',
      body: JSON.stringify(req),
    });
  }

  async getSupportedSites(): Promise<SiteInfo[]> {
    return this.fetch('/api/sites');
  }

  async checkUrl(url: string): Promise<{ supported: boolean; site?: SiteInfo }> {
    return this.fetch(`/api/sites/check?url=${encodeURIComponent(url)}`);
  }

  subscribe(listener: (event: DownloadEvent) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  dispose() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.listeners.clear();
  }
}
