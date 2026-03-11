import type { ManifestData, SiteInfo, DownloadEvent } from '../types';
import type {
  TransportAdapter,
  DiscoverRequest,
  DownloadRequest,
  ExpandRequest,
  DeleteNodesRequest,
} from './types';

interface VscodeApi {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
}

/**
 * VS Code Transport — communicates with extension host via postMessage.
 * Used when running inside a VS Code webview.
 */
export class VscodeTransport implements TransportAdapter {
  private vscode: VscodeApi;
  private listeners = new Set<(event: DownloadEvent) => void>();
  private pendingRequests = new Map<string, PendingRequest>();
  private requestId = 0;
  private messageHandler: (event: MessageEvent) => void;

  constructor(vscodeApi: VscodeApi) {
    this.vscode = vscodeApi;
    this.messageHandler = this.onMessage.bind(this);
    window.addEventListener('message', this.messageHandler);
  }

  private onMessage(event: MessageEvent) {
    const msg = event.data;
    if (!msg || typeof msg !== 'object') return;

    // Handle request-response
    if (msg._requestId && this.pendingRequests.has(msg._requestId)) {
      const pending = this.pendingRequests.get(msg._requestId)!;
      this.pendingRequests.delete(msg._requestId);
      if (msg._error) {
        pending.reject(new Error(msg._error));
      } else {
        pending.resolve(msg._data);
      }
      return;
    }

    // Handle push events — convert VS Code message format to DownloadEvent
    switch (msg.command) {
      case 'updateProgress':
        this.emit({
          type: 'progress',
          taskId: msg.resourceId || msg.event?.resourceId || '',
          data: msg.event || msg,
        });
        break;

      case 'updateManifest':
        this.emit({
          type: 'manifest_updated',
          taskId: msg.resourceId || '',
          data: { manifest: msg.manifest },
        });
        break;

      case 'taskCompleted':
        this.emit({
          type: 'task_completed',
          taskId: msg.resourceId || msg.taskId || '',
          data: {},
        });
        break;

      case 'taskError':
        this.emit({
          type: 'task_error',
          taskId: msg.resourceId || msg.taskId || '',
          data: { message: msg.message || msg.error || '' },
        });
        break;
    }
  }

  private emit(event: DownloadEvent) {
    for (const listener of this.listeners) {
      listener(event);
    }
  }

  private request<T>(command: string, data: Record<string, unknown> = {}): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const id = `req_${++this.requestId}`;
      this.pendingRequests.set(id, {
        resolve: resolve as (v: unknown) => void,
        reject,
      });
      this.vscode.postMessage({ command, _requestId: id, ...data });

      // Timeout after 60 seconds
      setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`Request ${command} timed out`));
        }
      }, 60000);
    });
  }

  async discover(req: DiscoverRequest): Promise<ManifestData> {
    return this.request('discoverResource', {
      url: req.url,
      outputDir: req.outputDir,
      depth: req.depth,
    });
  }

  async startDownload(req: DownloadRequest): Promise<void> {
    if (req.nodeIds?.length) {
      this.vscode.postMessage({
        command: 'downloadSelected',
        resourceId: req.taskId,
        nodeIds: req.nodeIds,
        concurrency: req.concurrency,
      });
    } else {
      this.vscode.postMessage({
        command: 'downloadAll',
        resourceId: req.taskId,
        concurrency: req.concurrency,
      });
    }
  }

  async cancelDownload(taskId: string): Promise<void> {
    this.vscode.postMessage({
      command: 'cancelDownload',
      resourceId: taskId,
    });
  }

  async expandNode(req: ExpandRequest): Promise<ManifestData> {
    return this.request('expandNode', {
      resourceId: req.taskId,
      nodeId: req.nodeId,
    });
  }

  async deleteNodes(req: DeleteNodesRequest): Promise<void> {
    this.vscode.postMessage({
      command: 'deleteNodes',
      resourceId: req.taskId,
      nodeIds: req.nodeIds,
    });
  }

  async getSupportedSites(): Promise<SiteInfo[]> {
    return this.request('getSupportedSites');
  }

  async checkUrl(url: string): Promise<{ supported: boolean; site?: SiteInfo }> {
    return this.request('checkUrl', { url });
  }

  subscribe(listener: (event: DownloadEvent) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  dispose() {
    window.removeEventListener('message', this.messageHandler);
    this.listeners.clear();
    for (const pending of this.pendingRequests.values()) {
      pending.reject(new Error('Transport disposed'));
    }
    this.pendingRequests.clear();
  }
}
