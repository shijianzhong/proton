import React, { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { FiCpu, FiEdit2, FiTrash2 } from 'react-icons/fi';
import styles from './AgentNode.module.css';

interface AgentNodeData {
  label: string;
  type: string;
  description?: string;
  routing_strategy?: string;
  onEdit?: () => void;
  onDelete?: () => void;
}

const typeLabels: Record<string, string> = {
  builtin: 'Built-in',
  native: 'Native',
  coze: 'Coze',
  dify: 'Dify',
  doubao: '豆包',
  autogen: 'AutoGen',
};

const AgentNode: React.FC<NodeProps<AgentNodeData>> = ({ data, selected }) => {
  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    data.onEdit?.();
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    data.onDelete?.();
  };

  return (
    <div className={`${styles.node} ${selected ? styles.selected : ''}`}>
      <Handle type="target" position={Position.Top} className={styles.handle} />

      <div className={styles.header}>
        <div className={styles.title}>
          <FiCpu className={styles.titleIcon} />
          <strong>{data.label}</strong>
        </div>
        <div className={styles.actions}>
          <button className={styles.actionButton} onClick={handleEdit} title="Edit">
            <FiEdit2 />
          </button>
          <button className={`${styles.actionButton} ${styles.actionButtonDanger}`} onClick={handleDelete} title="Delete">
            <FiTrash2 />
          </button>
        </div>
      </div>

      <div className={styles.tags}>
        <span className={styles.tag}>{typeLabels[data.type] || data.type}</span>
        {data.routing_strategy && (
          <span className={styles.tag}>{data.routing_strategy}</span>
        )}
      </div>

      {data.description && (
        <div className={styles.description}>
          {data.description}
        </div>
      )}
      
      <Handle type="source" position={Position.Bottom} className={styles.handle} />
    </div>
  );
};

export default memo(AgentNode);
