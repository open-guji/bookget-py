import React from 'react';
import { DownloadDashboard } from '../src/components/DownloadDashboard';
import { HttpTransport } from '../src/transport/http-transport';
import { MockTransport } from './mock-transport';
import '../src/styles/components.css';

// Use ?mock=1 in URL to use MockTransport (local dev without server)
// Otherwise connects to the bookget server (same origin in production, or via Vite proxy in dev)
const useMock = new URLSearchParams(location.search).has('mock');
const transport = useMock ? new MockTransport() : new HttpTransport('');

export const App: React.FC = () => {
  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bdm-bg)',
      color: 'var(--bdm-text)',
      fontFamily: 'var(--bdm-font-family)',
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 24px',
        borderBottom: '1px solid var(--bdm-card-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 20 }}>📚</span>
          <span style={{ fontSize: 16, fontWeight: 600 }}>Bookget</span>
          <span style={{ fontSize: 12, color: 'var(--bdm-text-dim)', marginLeft: 4 }}>古籍资源下载</span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--bdm-text-dim)' }}>
          {useMock ? '🟡 Mock 模式' : '🟢 已连接 bookget server'}
        </div>
      </div>

      {/* Main content */}
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 16px' }}>
        <DownloadDashboard
          transport={transport}
          showUrlInput={true}
          defaultOutputDir="./downloads"
        />
      </div>
    </div>
  );
};
