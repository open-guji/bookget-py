import React from 'react';
import { TaskCard, type TaskCardProps } from './TaskCard';

export interface TaskListProps {
  tasks: TaskCardProps[];
  onCancel?: (taskId: string) => void;
}

export const TaskList: React.FC<TaskListProps> = ({ tasks, onCancel }) => {
  const activeCount = tasks.filter(t => t.status === 'downloading').length;

  return (
    <div className="bdm-task-list">
      <div className="bdm-task-list-header">
        活跃下载 ({activeCount})
      </div>

      {tasks.length === 0 ? (
        <div className="bdm-task-list-empty">暂无下载任务</div>
      ) : (
        tasks.map(task => (
          <TaskCard key={task.id} {...task} onCancel={onCancel} />
        ))
      )}
    </div>
  );
};
