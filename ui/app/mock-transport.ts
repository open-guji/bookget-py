import type { ManifestData, SiteInfo, DownloadEvent } from '../src/types';
import type {
  TransportAdapter,
  DiscoverRequest,
  DownloadRequest,
  ExpandRequest,
  DeleteNodesRequest,
} from '../src/transport/types';

const MOCK_MANIFEST: ManifestData = {
  version: 1,
  book_id: 'mock-siku-001',
  source_url: 'https://ctext.org/siku-quanshu',
  source_site: 'ctext',
  title: '欽定四庫全書簡明目錄',
  metadata: { author: '紀昀 等', dynasty: '清' },
  discovery_complete: true,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  structure: {
    id: 'root',
    title: '欽定四庫全書簡明目錄',
    type: 'root',
    status: 'discovered',
    children: [
      {
        id: 'jing',
        title: '經部',
        type: 'section',
        status: 'completed',
        text_count: 12,
        children: [
          { id: 'jing-yi', title: '易類', type: 'chapter', status: 'completed', text_count: 3, image_count: 0 },
          { id: 'jing-shu', title: '書類', type: 'chapter', status: 'completed', text_count: 2, image_count: 0 },
          { id: 'jing-shi', title: '詩類', type: 'chapter', status: 'discovered', text_count: 3, image_count: 0 },
        ],
      },
      {
        id: 'shi',
        title: '史部',
        type: 'section',
        status: 'discovered',
        text_count: 15,
        children: [
          { id: 'shi-zheng', title: '正史類', type: 'chapter', status: 'discovered', text_count: 5 },
          { id: 'shi-bian', title: '編年類', type: 'chapter', status: 'pending', expandable: true },
          { id: 'shi-bie', title: '別史類', type: 'chapter', status: 'failed', text_count: 2 },
        ],
      },
      {
        id: 'zi',
        title: '子部',
        type: 'section',
        status: 'pending',
        expandable: true,
        children_count: 8,
      },
      {
        id: 'ji',
        title: '集部',
        type: 'section',
        status: 'downloading',
        text_count: 6,
        children: [
          { id: 'ji-chu', title: '楚辭類', type: 'chapter', status: 'downloading', text_count: 1 },
          { id: 'ji-bie', title: '別集類', type: 'chapter', status: 'discovered', text_count: 5 },
        ],
      },
    ],
  },
  progress: {
    total: 12,
    completed: 5,
    failed: 1,
    pending: 3,
    downloading: 2,
    percent: 42,
  },
};

const MOCK_SITES: SiteInfo[] = [
  { site_id: 'ctext', site_name: '中国哲学书电子化计划', site_domains: ['ctext.org'], supports_text: true, supports_images: false },
  { site_id: 'hanchi', site_name: '漢籍全文資料庫', site_domains: ['hanchi.ihp.sinica.edu.tw'], supports_text: true, supports_images: false },
  { site_id: 'archive_org', site_name: 'Internet Archive', site_domains: ['archive.org'], supports_text: false, supports_images: true },
  { site_id: 'ndl', site_name: '日本国立国会図書館', site_domains: ['dl.ndl.go.jp'], supports_text: false, supports_images: true },
];

/**
 * Mock transport for local UI development — simulates server responses.
 */
export class MockTransport implements TransportAdapter {
  private listeners = new Set<(event: DownloadEvent) => void>();
  private downloadTimers: ReturnType<typeof setInterval>[] = [];

  private emit(event: DownloadEvent) {
    for (const listener of this.listeners) listener(event);
  }

  async discover(req: DiscoverRequest): Promise<ManifestData> {
    // Simulate network delay
    await delay(800);
    console.log('[MockTransport] discover', req.url);
    return { ...MOCK_MANIFEST, source_url: req.url };
  }

  async startDownload(req: DownloadRequest): Promise<void> {
    console.log('[MockTransport] startDownload', req);
    // Simulate incremental progress events
    let progress = 0;
    const timer = setInterval(() => {
      progress += 10;
      this.emit({
        type: 'progress',
        taskId: req.taskId,
        data: {
          taskId: req.taskId,
          completed: Math.floor(progress / 10),
          total: 10,
          percent: progress,
        },
      });

      if (progress >= 100) {
        clearInterval(timer);
        this.emit({ type: 'task_completed', taskId: req.taskId, data: {} });
      }
    }, 500);
    this.downloadTimers.push(timer);
  }

  async cancelDownload(taskId: string): Promise<void> {
    console.log('[MockTransport] cancelDownload', taskId);
    this.emit({ type: 'task_error', taskId, data: { message: '已取消' } });
  }

  async expandNode(req: ExpandRequest): Promise<ManifestData> {
    await delay(600);
    console.log('[MockTransport] expandNode', req.nodeId);
    // Return manifest with the node expanded
    const manifest = JSON.parse(JSON.stringify(MOCK_MANIFEST)) as ManifestData;
    const node = findNode(manifest.structure, req.nodeId);
    if (node) {
      node.expandable = false;
      node.children = [
        { id: `${req.nodeId}-01`, title: `${node.title} · 卷一`, type: 'chapter', status: 'discovered', text_count: 2 },
        { id: `${req.nodeId}-02`, title: `${node.title} · 卷二`, type: 'chapter', status: 'discovered', text_count: 3 },
        { id: `${req.nodeId}-03`, title: `${node.title} · 卷三`, type: 'chapter', status: 'pending', text_count: 1 },
      ];
    }
    this.emit({ type: 'manifest_updated', taskId: req.taskId, data: { manifest } });
    return manifest;
  }

  async deleteNodes(req: DeleteNodesRequest): Promise<void> {
    console.log('[MockTransport] deleteNodes', req.nodeIds);
    await delay(300);
  }

  async getSupportedSites(): Promise<SiteInfo[]> {
    await delay(200);
    return MOCK_SITES;
  }

  async checkUrl(url: string): Promise<{ supported: boolean; site?: SiteInfo }> {
    await delay(300);
    const domain = new URL(url).hostname.replace('www.', '');
    const site = MOCK_SITES.find(s => s.site_domains.some(d => domain.includes(d)));
    return site ? { supported: true, site } : { supported: false };
  }

  subscribe(listener: (event: DownloadEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  dispose() {
    this.downloadTimers.forEach(t => clearInterval(t));
    this.downloadTimers = [];
    this.listeners.clear();
  }
}

function delay(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function findNode(node: ManifestData['structure'], id: string): ManifestData['structure'] | null {
  if (node.id === id) return node;
  for (const child of node.children ?? []) {
    const found = findNode(child, id);
    if (found) return found;
  }
  return null;
}
