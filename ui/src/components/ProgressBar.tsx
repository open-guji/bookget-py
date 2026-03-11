import React from 'react';

export interface ProgressBarProps {
  percent: number;
  status?: 'downloading' | 'completed' | 'error';
}

export const ProgressBar: React.FC<ProgressBarProps> = ({ percent, status = 'downloading' }) => {
  const cls = status === 'error' ? 'error' : status === 'completed' ? 'completed' : '';
  return (
    <div className="bdm-progress-container">
      <div
        className={`bdm-progress-fill ${cls}`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  );
};
