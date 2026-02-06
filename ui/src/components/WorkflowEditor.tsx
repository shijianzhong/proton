import React, { useCallback, useState, useEffect, FormEvent, useRef } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  MarkerType,
  Panel,
} from 'reactflow';
import 'reactflow/dist/style.css';
import AgentNode from './AgentNode';
import AgentEditor from './AgentEditor';
import ExecutionPanel from './ExecutionPanel';
import CopilotPanel from './CopilotPanel';
import { api, AgentTemplate } from '../api/client';
import styles from './WorkflowEditor.module.css';
import listStyles from './WorkflowList.module.css'; // Re-use styles

// --- Reusable custom components ---
const Modal: React.FC<{ isOpen: boolean; onClose: () => void; title: string; children: React.ReactNode }> = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;
  return (
    <div className={listStyles.modalOverlay} onClick={onClose}>
      <div className={listStyles.modalContent} onClick={(e) => e.stopPropagation()}>
        <h3 className={listStyles.modalHeader}>{title}</h3>
        {children}
      </div>
    </div>
  );
};
// --- End Reusable components ---


const nodeTypes = {
  agent: AgentNode,
};

interface WorkflowEditorProps {
  workflowId: string | null;
  onWorkflowCreated?: (id: string) => void;
}

const WorkflowEditor: React.FC<WorkflowEditorProps> = ({ workflowId, onWorkflowCreated }) => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const [currentWorkflowId, setCurrentWorkflowId] = useState<string | null>(workflowId);
  const [workflowName, setWorkflowName] = useState<string>('New Workflow');
  const [isSaving, setIsSaving] = useState(false);

  // Use ref to always have access to the latest workflowId in callbacks
  const currentWorkflowIdRef = useRef<string | null>(currentWorkflowId);
  useEffect(() => {
    currentWorkflowIdRef.current = currentWorkflowId;
  }, [currentWorkflowId]);

  // Modal states
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [templateModalVisible, setTemplateModalVisible] = useState(false);
  const [newWorkflowModalVisible, setNewWorkflowModalVisible] = useState(false);

  // Agent Editor state
  const [editorVisible, setEditorVisible] = useState(false);
  const [editingAgentId, setEditingAgentId] = useState<string | null>(null);
  const [editingAgentType, setEditingAgentType] = useState<string>('builtin');

  // Execution Panel state
  const [executionPanelVisible, setExecutionPanelVisible] = useState(false);

  // Copilot Panel state
  const [copilotVisible, setCopilotVisible] = useState(false);

  const [templates, setTemplates] = useState<AgentTemplate[]>([]);

  // New agent form state
  const [newAgentName, setNewAgentName] = useState('');
  const [newAgentDescription, setNewAgentDescription] = useState('');
  const [newAgentType, setNewAgentType] = useState('builtin');

  useEffect(() => {
    setCurrentWorkflowId(workflowId);
  }, [workflowId]);

  useEffect(() => {
    if (currentWorkflowId) {
      loadWorkflow(currentWorkflowId);
    } else {
      setNodes([]);
      setEdges([]);
      setWorkflowName('New Workflow');
    }
  }, [currentWorkflowId]);

  useEffect(() => {
    loadTemplates();
  }, []);

  // Use useCallback to create a stable reference for handleEditAgent
  const handleEditAgent = useCallback((agentId: string, agentType: string) => {
    // Use ref to get the latest workflowId
    if (!currentWorkflowIdRef.current) {
      alert('请先保存工作流后再编辑 Agent 配置');
      setNewWorkflowModalVisible(true);
      return;
    }
    setEditingAgentId(agentId);
    setEditingAgentType(agentType || 'builtin');
    setEditorVisible(true);
  }, []); // No dependencies - we use ref instead

  const loadWorkflow = async (id: string) => {
    try {
      const workflow = await api.getWorkflow(id);
      setWorkflowName(workflow.name || id);
      const flowNodes: Node[] = [];
      const flowEdges: Edge[] = [];
      if (workflow.tree?.nodes) {
        Object.values(workflow.tree.nodes).forEach((agent: any) => {
          flowNodes.push({
            id: agent.id,
            type: 'agent',
            position: { x: agent.parent_id ? 200 : 0, y: (flowNodes.length * 150) },
            data: {
              label: agent.name,
              type: agent.type,
              description: agent.description,
              routing_strategy: agent.routing_strategy,
              // Store agent info for callbacks - don't capture handleEditAgent directly
              onEdit: () => handleEditAgent(agent.id, agent.type),
              onDelete: () => handleDeleteAgent(agent.id),
            },
          });
          if (agent.parent_id) {
            flowEdges.push({
              id: `${agent.parent_id}-${agent.id}`,
              source: agent.parent_id,
              target: agent.id,
              markerEnd: { type: MarkerType.ArrowClosed },
            });
          }
        });
      }
      setNodes(flowNodes);
      setEdges(flowEdges);
    } catch (error) {
      alert('加载工作流失败');
    }
  };

  const handleDeleteAgent = useCallback(async (agentId: string) => {
    if (confirm('确定要删除这个 Agent 吗？')) {
      const wfId = currentWorkflowIdRef.current;
      if (wfId) {
        try {
          await api.removeAgent(wfId, agentId);
        } catch (error) {
          console.error('Failed to remove agent from backend:', error);
        }
      }
      setNodes((nds) => nds.filter((n) => n.id !== agentId));
      setEdges((eds) => eds.filter((e) => e.source !== agentId && e.target !== agentId));
    }
  }, [setNodes, setEdges]);

  const loadTemplates = async () => {
    try {
      setTemplates(await api.getTemplates());
    } catch (error) {
      console.error('Failed to load templates:', error);
    }
  };

  const onConnect = useCallback((params: Connection) => setEdges((eds) => addEdge({ ...params, markerEnd: { type: MarkerType.ArrowClosed } }, eds)), [setEdges]);

  const handleSaveWorkflow = async () => {
    if (!currentWorkflowId) {
      setNewWorkflowModalVisible(true);
      return;
    }
    setIsSaving(true);
    try {
      const existingAgents = await api.listAgents(currentWorkflowId);
      const existingIds = new Set(existingAgents.map((a: any) => a.id));
      for (const node of nodes) {
        if (!existingIds.has(node.id)) {
          await api.addAgent(currentWorkflowId, {
            name: node.data.label,
            description: node.data.description || '',
            type: node.data.type || 'builtin',
            parent_id: edges.find(e => e.target === node.id)?.source,
          });
        }
      }
      alert('工作流已保存');
    } catch (error) {
      console.error('Failed to save workflow:', error);
      alert('保存工作流失败');
    } finally {
      setIsSaving(false);
    }
  };

    const handleCreateNewWorkflow = async (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const formData = new FormData(e.currentTarget);
        const name = formData.get('name') as string;
        const description = formData.get('description') as string;

        setIsSaving(true);
        try {
            const workflow = await api.createWorkflow({ name, description });
            setCurrentWorkflowId(workflow.id);
            setWorkflowName(workflow.name);
            setNewWorkflowModalVisible(false);
            onWorkflowCreated?.(workflow.id);

            for (const node of nodes) {
                const parentEdge = edges.find(e => e.target === node.id);
                await api.addAgent(workflow.id, {
                    name: node.data.label,
                    description: node.data.description || '',
                    type: node.data.type || 'builtin',
                    parent_id: parentEdge?.source,
                });
            }
            alert('工作流创建并保存成功');
        } catch (error) {
            console.error('Failed to create workflow:', error);
            alert('创建工作流失败');
        } finally {
            setIsSaving(false);
        }
    };

  const handleRunWorkflow = async () => {
    if (!currentWorkflowId) {
      alert('请先保存工作流');
      return;
    }
    // Open the ExecutionPanel instead of using prompt/alert
    setExecutionPanelVisible(true);
  };

  // handleEditAgent is now stable via useCallback, so no need for currentWorkflowId dependency
  const handleNodeDoubleClick = useCallback((_: any, node: Node) => handleEditAgent(node.id, node.data.type || 'builtin'), [handleEditAgent]);

  const handleAddBlankAgent = useCallback(async () => {
    if (!newAgentName.trim()) {
      alert('请输入 Agent 名称');
      return;
    }
    const wfId = currentWorkflowIdRef.current;
    if (!wfId) {
      alert('请先保存工作流');
      setNewWorkflowModalVisible(true);
      setIsAddModalOpen(false);
      return;
    }

    try {
      // Save to backend first, get real ID
      const result = await api.addAgent(wfId, {
        name: newAgentName,
        description: newAgentDescription,
        type: newAgentType,
      });

      const newNode: Node = {
        id: result.id,
        type: 'agent',
        position: { x: Math.random() * 300, y: nodes.length * 150 },
        data: {
          label: newAgentName,
          type: newAgentType,
          description: newAgentDescription,
          onEdit: () => handleEditAgent(result.id, newAgentType),
          onDelete: () => handleDeleteAgent(result.id),
        },
      };
      setNodes((nds) => [...nds, newNode]);
      setIsAddModalOpen(false);
      setNewAgentName('');
      setNewAgentDescription('');
      setNewAgentType('builtin');
    } catch (error) {
      console.error('Failed to add agent:', error);
      alert('添加 Agent 失败');
    }
  }, [newAgentName, newAgentDescription, newAgentType, nodes.length, handleEditAgent, handleDeleteAgent, setNodes]);

  const handleAddFromTemplate = useCallback(async (template: AgentTemplate) => {
    const wfId = currentWorkflowIdRef.current;
    if (!wfId) {
      alert('请先保存工作流');
      setNewWorkflowModalVisible(true);
      setTemplateModalVisible(false);
      return;
    }

    try {
      // Create agent from template via backend
      const result = await api.createAgentFromTemplate(wfId, template.id, template.name);

      const newNode: Node = {
        id: result.id,
        type: 'agent',
        position: { x: Math.random() * 300, y: nodes.length * 150 },
        data: {
          label: result.name || template.name,
          type: 'builtin',
          description: template.description,
          onEdit: () => handleEditAgent(result.id, 'builtin'),
          onDelete: () => handleDeleteAgent(result.id),
        },
      };
      setNodes((nds) => [...nds, newNode]);
      setTemplateModalVisible(false);
    } catch (error) {
      console.error('Failed to add agent from template:', error);
      alert('从模板添加 Agent 失败');
    }
  }, [nodes.length, handleEditAgent, handleDeleteAgent, setNodes]);

  return (
    <div className={styles.editorWrapper}>
      <div className={styles.header}>
        <h2 className={styles.title}>工作流编辑器</h2>
        <div className={styles.actions}>
          <div className={styles.dropdown}>
            <button className={styles.button}>添加 Agent</button>
            <div className={styles.dropdownContent}>
              <a className={styles.dropdownItem} onClick={() => setIsAddModalOpen(true)}>空白 Agent</a>
              <a className={styles.dropdownItem} onClick={() => setTemplateModalVisible(true)}>从模板创建</a>
            </div>
          </div>
          <button className={styles.button} onClick={handleSaveWorkflow} disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </button>
          <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleRunWorkflow} disabled={!currentWorkflowId}>
            运行
          </button>
          <button className={styles.button} onClick={() => setCopilotVisible(true)}>
            🤖 AI Copilot
          </button>
        </div>
      </div>

      <div className={styles.flowContainer}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          onNodeDoubleClick={handleNodeDoubleClick}
          fitView
        >
          <Controls />
          <Background />
          <Panel position="top-left">
            <div className={styles.panel}>
              <b>{currentWorkflowId ? workflowName : '📝 新工作流 (未保存)'}</b>
            </div>
          </Panel>
        </ReactFlow>
      </div>

      <Modal isOpen={newWorkflowModalVisible} onClose={() => setNewWorkflowModalVisible(false)} title="创建新工作流">
        <form onSubmit={handleCreateNewWorkflow}>
          <div className={listStyles.formGroup}>
            <label className={listStyles.formLabel} htmlFor="name">工作流名称</label>
            <input id="name" name="name" className={listStyles.formInput} type="text" required />
          </div>
          <div className={listStyles.formGroup}>
            <label className={listStyles.formLabel} htmlFor="description">描述</label>
            <textarea id="description" name="description" className={listStyles.formTextarea} />
          </div>
          <div className={listStyles.modalFooter}>
            <button type="button" className={listStyles.buttonLink} onClick={() => setNewWorkflowModalVisible(false)}>取消</button>
            <button type="submit" className={`${listStyles.button} ${listStyles.buttonPrimary}`} disabled={isSaving}>
              {isSaving ? '创建中...' : '创建并保存'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={isAddModalOpen} onClose={() => setIsAddModalOpen(false)} title="添加空白 Agent">
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Agent 名称</label>
          <input
            className={listStyles.formInput}
            type="text"
            value={newAgentName}
            onChange={(e) => setNewAgentName(e.target.value)}
            placeholder="请输入 Agent 名称"
          />
        </div>
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>描述</label>
          <textarea
            className={listStyles.formTextarea}
            value={newAgentDescription}
            onChange={(e) => setNewAgentDescription(e.target.value)}
            placeholder="请输入描述 (可选)"
          />
        </div>
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Agent 类型</label>
          <select
            className={listStyles.formInput}
            value={newAgentType}
            onChange={(e) => setNewAgentType(e.target.value)}
          >
            <option value="builtin">内置 (Built-in)</option>
            <option value="native">原生 (Native)</option>
            <option value="coze">Coze</option>
            <option value="dify">Dify</option>
            <option value="doubao">豆包 (Doubao)</option>
            <option value="autogen">AutoGen</option>
            <option value="custom">自定义 (Custom)</option>
          </select>
        </div>
        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setIsAddModalOpen(false)}>取消</button>
          <button
            type="button"
            className={`${listStyles.button} ${listStyles.buttonPrimary}`}
            onClick={handleAddBlankAgent}
          >
            添加 Agent
          </button>
        </div>
      </Modal>

      <Modal isOpen={templateModalVisible} onClose={() => setTemplateModalVisible(false)} title="选择模板">
        <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
          {templates.length === 0 ? (
            <p>暂无可用模板</p>
          ) : (
            templates.map((template) => (
              <div
                key={template.id}
                className={styles.templateItem}
                onClick={() => handleAddFromTemplate(template)}
                style={{
                  padding: '12px',
                  margin: '8px 0',
                  border: '1px solid #e0e0e0',
                  borderRadius: '8px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontWeight: 'bold' }}>{template.name}</div>
                <div style={{ fontSize: '12px', color: '#666' }}>{template.description}</div>
                <div style={{ fontSize: '11px', color: '#999', marginTop: '4px' }}>
                  分类: {template.category} {template.is_official && '• 官方'}
                </div>
              </div>
            ))
          )}
        </div>
        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setTemplateModalVisible(false)}>取消</button>
        </div>
      </Modal>

      <AgentEditor
        visible={editorVisible}
        workflowId={currentWorkflowId || ''}
        agentId={editingAgentId}
        agentType={editingAgentType}
        onClose={() => setEditorVisible(false)}
        onSave={() => currentWorkflowId && loadWorkflow(currentWorkflowId)}
      />

      <ExecutionPanel
        visible={executionPanelVisible}
        workflowId={currentWorkflowId}
        workflowName={workflowName}
        onClose={() => setExecutionPanelVisible(false)}
      />

      <CopilotPanel
        visible={copilotVisible}
        workflowId={currentWorkflowId}
        onClose={() => setCopilotVisible(false)}
        onWorkflowGenerated={(id) => {
          setCurrentWorkflowId(id);
          loadWorkflow(id);
          setCopilotVisible(false);
        }}
      />
    </div>
  );
};

export default WorkflowEditor;
