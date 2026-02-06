import React, { useEffect, useState, FormEvent } from 'react';
import { api, WorkflowTemplate, WorkflowTemplateDetail } from '../api/client';
import styles from './WorkflowList.module.css';

interface Workflow {
  id: string;
  name: string;
  description: string;
  state: string;
  agent_count: number;
  created_at: string;
  updated_at: string;
}

interface WorkflowListProps {
  onSelect: (id: string) => void;
}

// A simple, custom modal component
const Modal: React.FC<{ isOpen: boolean; onClose: () => void; title: string; children: React.ReactNode }> = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;
  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
        <h3 className={styles.modalHeader}>{title}</h3>
        {children}
      </div>
    </div>
  );
};

// Icon mapping
const iconMap: Record<string, string> = {
  plane: '✈️',
  compass: '🧭',
  map: '🗺️',
  building: '🏨',
  utensils: '🍽️',
  calculator: '💰',
  globe: '🌍',
  'laptop-code': '💻',
  crown: '👑',
  sitemap: '🏗️',
  desktop: '🖥️',
  server: '⚙️',
  bug: '🐛',
  'pen-fancy': '✍️',
  robot: '🤖',
  code: '📝',
  share: '🔀',
  chart: '📊',
  edit: '✏️',
  headset: '🎧',
};

const WorkflowList: React.FC<WorkflowListProps> = ({ onSelect }) => {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');

  // Workflow template states
  const [wfTemplateModalOpen, setWfTemplateModalOpen] = useState(false);
  const [wfTemplates, setWfTemplates] = useState<WorkflowTemplate[]>([]);
  const [wfTemplateDetail, setWfTemplateDetail] = useState<WorkflowTemplateDetail | null>(null);
  const [wfTemplateDetailOpen, setWfTemplateDetailOpen] = useState(false);
  const [creatingFromTemplate, setCreatingFromTemplate] = useState(false);

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    setLoading(true);
    try {
      const data = await api.listWorkflows();
      setWorkflows(data);
    } catch (error) {
      alert('加载工作流失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.createWorkflow({ name: newName, description: newDescription });
      alert('工作流已创建');
      setIsCreateModalOpen(false);
      setNewName('');
      setNewDescription('');
      loadWorkflows();
    } catch (error) {
      alert('创建工作流失败');
    }
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('确定要删除这个工作流吗？')) {
      try {
        await api.deleteWorkflow(id);
        alert('工作流已删除');
        loadWorkflows();
      } catch (error) {
        alert('删除工作流失败');
      }
    }
  };

  const handleRun = async (id: string) => {
    const input = prompt('请输入消息:');
    if (!input) return;

    try {
      const result = await api.runWorkflow(id, input);
      alert(`工作流已执行: ${result.state}`);
      if (result.output) {
        alert(`输出:\n${result.output}`);
      }
    } catch (error) {
      alert('运行工作流失败');
    }
  };

  const handleOpenWfTemplates = async () => {
    try {
      const templates = await api.listWorkflowTemplates();
      setWfTemplates(templates);
      setWfTemplateModalOpen(true);
    } catch (error) {
      alert('加载工作流模板失败');
    }
  };

  const handleViewTemplateDetail = async (templateId: string) => {
    try {
      const detail = await api.getWorkflowTemplate(templateId);
      setWfTemplateDetail(detail);
      setWfTemplateDetailOpen(true);
    } catch (error) {
      alert('加载模板详情失败');
    }
  };

  const handleCreateFromTemplate = async (templateId: string) => {
    setCreatingFromTemplate(true);
    try {
      const result = await api.createWorkflowFromTemplate(templateId);
      setWfTemplateDetailOpen(false);
      setWfTemplateModalOpen(false);
      loadWorkflows();
      alert(`工作流 "${result.name}" 已创建，包含 ${result.agent_count} 个 Agent！`);
      onSelect(result.workflow_id);
    } catch (error) {
      alert('从模板创建工作流失败');
    } finally {
      setCreatingFromTemplate(false);
    }
  };

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>工作流列表</h2>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            className={styles.button}
            onClick={handleOpenWfTemplates}
          >
            从模板创建
          </button>
          <button
            className={`${styles.button} ${styles.buttonPrimary}`}
            onClick={() => setIsCreateModalOpen(true)}
          >
            创建工作流
          </button>
        </div>
      </div>

      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>名称</th>
              <th>描述</th>
              <th>状态</th>
              <th>Agent 数</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6}>加载中...</td></tr>
            ) : (
              workflows.map((wf) => (
                <tr key={wf.id}>
                  <td><a className={styles.nameLink} onClick={() => onSelect(wf.id)}>{wf.name}</a></td>
                  <td>{wf.description}</td>
                  <td><span className={styles.tag} style={{ backgroundColor: 'var(--color-secondary)' }}>{wf.state}</span></td>
                  <td>{wf.agent_count}</td>
                  <td>{new Date(wf.updated_at).toLocaleString()}</td>
                  <td>
                    <button className={styles.buttonLink} onClick={() => handleRun(wf.id)}>运行</button>
                    <button className={`${styles.buttonLink} ${styles.buttonLinkDanger}`} onClick={() => handleDelete(wf.id)}>删除</button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Create Workflow Modal */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title="创建工作流"
      >
        <form onSubmit={handleCreate}>
          <div className={styles.formGroup}>
            <label className={styles.formLabel} htmlFor="name">名称</label>
            <input
              id="name"
              className={styles.formInput}
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
            />
          </div>
          <div className={styles.formGroup}>
            <label className={styles.formLabel} htmlFor="description">描述</label>
            <textarea
              id="description"
              className={styles.formTextarea}
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
            />
          </div>
          <div className={styles.modalFooter}>
            <button type="button" className={styles.buttonLink} onClick={() => setIsCreateModalOpen(false)}>取消</button>
            <button type="submit" className={`${styles.button} ${styles.buttonPrimary}`}>创建</button>
          </div>
        </form>
      </Modal>

      {/* Workflow Templates Modal */}
      <Modal
        isOpen={wfTemplateModalOpen}
        onClose={() => setWfTemplateModalOpen(false)}
        title="工作流模板"
      >
        <p style={{ color: '#999', marginBottom: '16px' }}>
          选择一个模板来创建包含预配置 Agent 的完整工作流
        </p>
        <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
          {wfTemplates.map((tpl) => (
            <div
              key={tpl.id}
              onClick={() => handleViewTemplateDetail(tpl.id)}
              style={{
                padding: '16px',
                margin: '8px 0',
                border: '1px solid var(--color-secondary)',
                borderRadius: '8px',
                cursor: 'pointer',
                transition: 'border-color 0.2s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-cta)')}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-secondary)')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                <span style={{ fontSize: '1.5rem' }}>{iconMap[tpl.icon] || '📦'}</span>
                <div>
                  <div style={{ fontWeight: 'bold', fontSize: '1rem' }}>{tpl.name}</div>
                  <div style={{ fontSize: '0.8rem', color: '#888' }}>
                    {tpl.agent_count} 个 Agent · {tpl.category}
                    {tpl.is_official && ' · 官方'}
                  </div>
                </div>
              </div>
              <div style={{ fontSize: '0.85rem', color: '#aaa' }}>{tpl.description}</div>
            </div>
          ))}
        </div>
        <div className={styles.modalFooter}>
          <button type="button" className={styles.buttonLink} onClick={() => setWfTemplateModalOpen(false)}>关闭</button>
        </div>
      </Modal>

      {/* Template Detail Modal */}
      <Modal
        isOpen={wfTemplateDetailOpen}
        onClose={() => setWfTemplateDetailOpen(false)}
        title={wfTemplateDetail ? `${iconMap[wfTemplateDetail.icon] || '📦'} ${wfTemplateDetail.name}` : '模板详情'}
      >
        {wfTemplateDetail && (
          <>
            <p style={{ color: '#aaa', marginBottom: '20px' }}>{wfTemplateDetail.description}</p>

            <h4 style={{ marginBottom: '12px' }}>Agent 团队结构</h4>
            <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
              {/* Root agents */}
              {wfTemplateDetail.agents
                .filter(a => !a.parent_ref)
                .map(rootAgent => (
                  <div key={rootAgent.ref_id} style={{ marginBottom: '16px' }}>
                    <div style={{
                      padding: '12px',
                      border: '2px solid var(--color-cta)',
                      borderRadius: '8px',
                      background: 'rgba(var(--color-cta-rgb, 99, 102, 241), 0.1)',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '1.2rem' }}>{iconMap[rootAgent.icon] || '🤖'}</span>
                        <div>
                          <div style={{ fontWeight: 'bold' }}>{rootAgent.name}</div>
                          <div style={{ fontSize: '0.8rem', color: '#888' }}>协调者</div>
                        </div>
                      </div>
                      <div style={{ fontSize: '0.85rem', color: '#aaa', marginTop: '6px' }}>{rootAgent.description}</div>
                    </div>

                    {/* Child agents */}
                    <div style={{ marginLeft: '24px', borderLeft: '2px solid var(--color-secondary)', paddingLeft: '16px', marginTop: '8px' }}>
                      {wfTemplateDetail.agents
                        .filter(a => a.parent_ref === rootAgent.ref_id)
                        .map(child => (
                          <div key={child.ref_id} style={{
                            padding: '10px',
                            margin: '6px 0',
                            border: '1px solid var(--color-secondary)',
                            borderRadius: '6px',
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span>{iconMap[child.icon] || '🤖'}</span>
                              <div>
                                <div style={{ fontWeight: '600', fontSize: '0.9rem' }}>{child.name}</div>
                                <div style={{ fontSize: '0.8rem', color: '#888' }}>{child.description}</div>
                              </div>
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                ))}
            </div>

            <div className={styles.modalFooter}>
              <button type="button" className={styles.buttonLink} onClick={() => setWfTemplateDetailOpen(false)}>返回</button>
              <button
                type="button"
                className={`${styles.button} ${styles.buttonPrimary}`}
                onClick={() => handleCreateFromTemplate(wfTemplateDetail.id)}
                disabled={creatingFromTemplate}
              >
                {creatingFromTemplate ? '创建中...' : `创建工作流 (${wfTemplateDetail.agents.length} 个 Agent)`}
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
};

export default WorkflowList;
