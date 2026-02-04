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
      alert('Please save the workflow first before editing agent configuration');
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
      alert('Failed to load workflow');
    }
  };

  const handleDeleteAgent = useCallback(async (agentId: string) => {
    if (confirm('Are you sure you want to delete this agent?')) {
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
      alert('Workflow saved');
    } catch (error) {
      console.error('Failed to save workflow:', error);
      alert('Failed to save workflow');
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
            alert('Workflow created and saved');
        } catch (error) {
            console.error('Failed to create workflow:', error);
            alert('Failed to create workflow');
        } finally {
            setIsSaving(false);
        }
    };

  const handleRunWorkflow = async () => {
    if (!currentWorkflowId) {
      alert('Please save the workflow first');
      return;
    }
    const input = prompt('Enter your message:');
    if (!input) return;
    try {
      const result = await api.runWorkflow(currentWorkflowId, input);
      alert(`Workflow completed: ${result.state}\n\nOutput:\n${result.output}`);
    } catch (error) {
      alert('Failed to run workflow');
    }
  };

  // handleEditAgent is now stable via useCallback, so no need for currentWorkflowId dependency
  const handleNodeDoubleClick = useCallback((_: any, node: Node) => handleEditAgent(node.id, node.data.type || 'builtin'), [handleEditAgent]);

  const handleAddBlankAgent = useCallback(async () => {
    if (!newAgentName.trim()) {
      alert('Please enter an agent name');
      return;
    }
    const wfId = currentWorkflowIdRef.current;
    if (!wfId) {
      alert('Please save the workflow first');
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
      alert('Failed to add agent');
    }
  }, [newAgentName, newAgentDescription, newAgentType, nodes.length, handleEditAgent, handleDeleteAgent, setNodes]);

  const handleAddFromTemplate = useCallback(async (template: AgentTemplate) => {
    const wfId = currentWorkflowIdRef.current;
    if (!wfId) {
      alert('Please save the workflow first');
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
      alert('Failed to add agent from template');
    }
  }, [nodes.length, handleEditAgent, handleDeleteAgent, setNodes]);

  return (
    <div className={styles.editorWrapper}>
      <div className={styles.header}>
        <h2 className={styles.title}>Workflow Editor</h2>
        <div className={styles.actions}>
          <div className={styles.dropdown}>
            <button className={styles.button}>Add Agent</button>
            <div className={styles.dropdownContent}>
              <a className={styles.dropdownItem} onClick={() => setIsAddModalOpen(true)}>Blank Agent</a>
              <a className={styles.dropdownItem} onClick={() => setTemplateModalVisible(true)}>From Template</a>
            </div>
          </div>
          <button className={styles.button} onClick={handleSaveWorkflow} disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save'}
          </button>
          <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleRunWorkflow} disabled={!currentWorkflowId}>
            Run
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
              <b>{currentWorkflowId ? workflowName : '📝 New Workflow (unsaved)'}</b>
            </div>
          </Panel>
        </ReactFlow>
      </div>

      <Modal isOpen={newWorkflowModalVisible} onClose={() => setNewWorkflowModalVisible(false)} title="Create New Workflow">
        <form onSubmit={handleCreateNewWorkflow}>
          <div className={listStyles.formGroup}>
            <label className={listStyles.formLabel} htmlFor="name">Workflow Name</label>
            <input id="name" name="name" className={listStyles.formInput} type="text" required />
          </div>
          <div className={listStyles.formGroup}>
            <label className={listStyles.formLabel} htmlFor="description">Description</label>
            <textarea id="description" name="description" className={listStyles.formTextarea} />
          </div>
          <div className={listStyles.modalFooter}>
            <button type="button" className={listStyles.buttonLink} onClick={() => setNewWorkflowModalVisible(false)}>Cancel</button>
            <button type="submit" className={`${listStyles.button} ${listStyles.buttonPrimary}`} disabled={isSaving}>
              {isSaving ? 'Creating...' : 'Create & Save'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={isAddModalOpen} onClose={() => setIsAddModalOpen(false)} title="Add Blank Agent">
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Agent Name</label>
          <input
            className={listStyles.formInput}
            type="text"
            value={newAgentName}
            onChange={(e) => setNewAgentName(e.target.value)}
            placeholder="Enter agent name"
          />
        </div>
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Description</label>
          <textarea
            className={listStyles.formTextarea}
            value={newAgentDescription}
            onChange={(e) => setNewAgentDescription(e.target.value)}
            placeholder="Enter description (optional)"
          />
        </div>
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Agent Type</label>
          <select
            className={listStyles.formInput}
            value={newAgentType}
            onChange={(e) => setNewAgentType(e.target.value)}
          >
            <option value="builtin">Built-in</option>
            <option value="native">Native</option>
            <option value="coze">Coze</option>
            <option value="dify">Dify</option>
            <option value="doubao">Doubao</option>
            <option value="autogen">AutoGen</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setIsAddModalOpen(false)}>Cancel</button>
          <button
            type="button"
            className={`${listStyles.button} ${listStyles.buttonPrimary}`}
            onClick={handleAddBlankAgent}
          >
            Add Agent
          </button>
        </div>
      </Modal>

      <Modal isOpen={templateModalVisible} onClose={() => setTemplateModalVisible(false)} title="Select Template">
        <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
          {templates.length === 0 ? (
            <p>No templates available</p>
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
                  Category: {template.category} {template.is_official && '• Official'}
                </div>
              </div>
            ))
          )}
        </div>
        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setTemplateModalVisible(false)}>Cancel</button>
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
    </div>
  );
};

export default WorkflowEditor;
