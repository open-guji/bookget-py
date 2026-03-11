import React from 'react';

export interface TaskCardProps {
  id: string;
  name: string;
  progress: number;
  status: 'downloading' | 'completed' | 'error';
  message?: string;
  onCancel?: (id: string) => void;
}

export const TaskCard: React.FC<TaskCardProps> = ({
  id, name, progress, status, message, onCancel,
}) => {
  const barColor = status === 'error'
    ? 'var(--bdm-error)'
    : status === 'completed'
      ? 'var(--bdm-success)'
      : 'var(--bdm-accent)';

  const statusText = message
    || (status === 'downloading' ? '下载中...'
      : status === 'completed' ? '已完成'
      : '停止');

  return (
    <div className={`bdm-task-card ${status}`}>
      <div className="bdm-task-header">
        <div className="bdm-task-name" title={name}>{name}</div>
        <div className="bdm-task-percent">{progress}%</div>
      </div>

      <div className="bdm-task-progress-bar">
        <div
          className="bdm-task-progress-fill"
          style={{ width: `${progress}%`, background: barColor }}
        />
      </div>

      <div className="bdm-task-footer">
        <div
          className="bdm-task-message"
          style={{ color: status === 'error' ? 'var(--bdm-error)' : 'var(--bdm-text-dim)' }}
        >
          {statusText}
        </div>
        {status === 'downloading' && onCancel && (
          <button className="bdm-btn" onClick={() => onCancel(id)}>
            取消
          </button>
        )}
      </div>
    </div>
  );
};
