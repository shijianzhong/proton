import React, { useState, useEffect, useRef } from 'react';
import { api, AgentDefinition, BuiltinTool, ToolParameter, SystemTool } from '../api/client';
import styles from './AgentEditor.module.css';
import listStyles from './WorkflowList.module.css';

interface AgentEditorProps {
  visible: boolean;
  workflowId: string;
  agentId: string | null;
  agentType: string;
  onClose: () => void;
  onSave: () => void;
}

// Reusable Modal
const Modal: React.FC<{ isOpen: boolean; onClose: () => void; title: string; children: React.ReactNode }> = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;
  return (
    <div className={listStyles.modalOverlay} onClick={onClose}>
      <div className={listStyles.modalContent} onClick={(e) => e.stopPropagation()} style={{ maxWidth: '600px', maxHeight: '90vh', overflow: 'auto' }}>
        <h3 className={listStyles.modalHeader}>{title}</h3>
        {children}
      </div>
    </div>
  );
};

// Plugin interface
interface Plugin {
  id: string;
  type: 'mcp' | 'skill' | 'rag';
  name: string;
  enabled: boolean;
  tools?: string[];
  config?: any;
}

const AgentEditor: React.FC<AgentEditorProps> = ({ visible, workflowId, agentId, agentType, onClose, onSave }) => {
  const [definition, setDefinition] = useState<AgentDefinition | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('basic');
  const [formData, setFormData] = useState<Partial<AgentDefinition>>({});

  // Modal states
  const [testModalVisible, setTestModalVisible] = useState(false);
  const [testMessage, setTestMessage] = useState('');
  const [testLoading, setTestLoading] = useState(false);

  // Chat interface state
  const [chatMessages, setChatMessages] = useState<Array<{role: 'user' | 'assistant'; content: string}>>([]);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [chatMessages, testLoading]);

  // Tool modal states
  const [toolModalVisible, setToolModalVisible] = useState(false);
  const [editingTool, setEditingTool] = useState<BuiltinTool | null>(null);
  const [toolForm, setToolForm] = useState<Partial<BuiltinTool>>({
    name: '',
    description: '',
    tool_type: 'http',
    parameters: [],
    http_method: 'GET',
    http_url: '',
    timeout: 30,
  });

  // Plugin modal states
  const [pluginModalVisible, setPluginModalVisible] = useState(false);
  const [pluginType, setPluginType] = useState<'mcp' | 'skill' | 'rag'>('mcp');
  const [pluginForm, setPluginForm] = useState<any>({});
  const [plugins, setPlugins] = useState<Plugin[]>([]);

  // System tools state
  const [systemTools, setSystemTools] = useState<Record<string, SystemTool[]>>({});
  const [systemToolCategories, setSystemToolCategories] = useState<string[]>([]);

  // Parameter modal states
  const [paramModalVisible, setParamModalVisible] = useState(false);
  const [paramForm, setParamForm] = useState<Partial<ToolParameter>>({
    name: '',
    type: 'string',
    description: '',
    required: false,
  });

  useEffect(() => {
    if (visible && workflowId && agentId && agentType === 'builtin') {
      loadDefinition();
      loadPlugins();
      loadSystemTools();
    } else if (visible) {
      setDefinition(null);
      setFormData({});
    }
  }, [visible, workflowId, agentId, agentType]);

  const loadSystemTools = async () => {
    try {
      const data = await api.getSystemToolsByCategory();
      setSystemToolCategories(data.categories);
      setSystemTools(data.tools_by_category);
    } catch (error) {
      console.error('Failed to load system tools:', error);
    }
  };

  const loadDefinition = async () => {
    if (!workflowId || !agentId) return;
    setLoading(true);
    try {
      const def = await api.getAgentDefinition(workflowId, agentId);
      setDefinition(def);
      // Extract builtin_definition fields to formData for editing
      if (def.builtin_definition) {
        setFormData({
          ...def.builtin_definition,
          // Also include node-level fields
          routing_strategy: def.routing_strategy,
          max_depth: def.max_depth,
          timeout: def.timeout,
          enabled: def.enabled,
        });
      } else {
        // Fallback: use basic fields
        setFormData({
          name: def.name,
          description: def.description,
        });
      }
    } catch (error) {
      console.error('Failed to load definition:', error);
      setDefinition(null);
      setFormData({});
    } finally {
      setLoading(false);
    }
  };

  const loadPlugins = async () => {
    try {
      const list = await api.listPlugins();
      setPlugins(list);
    } catch (error) {
      console.error('Failed to load plugins:', error);
    }
  };

  const handleFormChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;

    if (type === 'number') {
      setFormData(prev => ({ ...prev, [name]: parseFloat(value) || 0 }));
    } else if (type === 'checkbox') {
      setFormData(prev => ({ ...prev, [name]: checked }));
    } else {
      setFormData(prev => ({ ...prev, [name]: value }));
    }
  };

  const handleSave = async () => {
    if (!workflowId || !agentId) return;
    setLoading(true);
    try {
      // Separate node-level fields from builtin_definition fields
      const { routing_strategy, max_depth, timeout, enabled, ...builtinFields } = formData;

      // Build the update payload
      const updatePayload: any = {
        name: formData.name,
        description: formData.description,
      };

      // Add node-level fields if present
      if (routing_strategy !== undefined) updatePayload.routing_strategy = routing_strategy;
      if (max_depth !== undefined) updatePayload.max_depth = max_depth;
      if (timeout !== undefined) updatePayload.timeout = timeout;
      if (enabled !== undefined) updatePayload.enabled = enabled;

      // Wrap builtin fields in builtin_definition
      updatePayload.builtin_definition = builtinFields;

      await api.updateAgentDefinition(workflowId, agentId, updatePayload);
      alert('Agent definition saved');
      onSave();
    } catch (error) {
      alert('Failed to save agent definition');
    } finally {
      setLoading(false);
    }
  };

  // Tool management
  const handleAddTool = () => {
    setEditingTool(null);
    setToolForm({
      name: '',
      description: '',
      tool_type: 'http',
      parameters: [],
      http_method: 'GET',
      http_url: '',
      timeout: 30,
    });
    setToolModalVisible(true);
  };

  const handleEditTool = (tool: BuiltinTool) => {
    setEditingTool(tool);
    setToolForm({ ...tool });
    setToolModalVisible(true);
  };

  const handleDeleteTool = async (toolName: string) => {
    if (!confirm(`Delete tool "${toolName}"?`)) return;
    if (!workflowId || !agentId) return;

    try {
      await api.deleteTool(workflowId, agentId, toolName);
      setFormData(prev => ({
        ...prev,
        builtin_tools: (prev.builtin_tools || []).filter(t => t.name !== toolName)
      }));
    } catch (error) {
      alert('Failed to delete tool');
    }
  };

  const handleSaveTool = async () => {
    if (!workflowId || !agentId) return;
    if (!toolForm.name || !toolForm.description) {
      alert('Tool name and description are required');
      return;
    }

    try {
      await api.addTool(workflowId, agentId, toolForm as BuiltinTool);
      setToolModalVisible(false);
      loadDefinition();
    } catch (error) {
      alert('Failed to save tool');
    }
  };

  // Parameter management for tools
  const handleAddParameter = () => {
    setParamForm({ name: '', type: 'string', description: '', required: false });
    setParamModalVisible(true);
  };

  const handleSaveParameter = () => {
    if (!paramForm.name) {
      alert('Parameter name is required');
      return;
    }
    setToolForm(prev => ({
      ...prev,
      parameters: [...(prev.parameters || []), paramForm as ToolParameter]
    }));
    setParamModalVisible(false);
  };

  const handleDeleteParameter = (paramName: string) => {
    setToolForm(prev => ({
      ...prev,
      parameters: (prev.parameters || []).filter(p => p.name !== paramName)
    }));
  };

  // Plugin management
  const handleAddPlugin = (type: 'mcp' | 'skill' | 'rag') => {
    setPluginType(type);
    setPluginForm({});
    setPluginModalVisible(true);
  };

  const handleSavePlugin = async () => {
    try {
      if (pluginType === 'mcp') {
        await api.registerMCP({
          name: pluginForm.name,
          command: pluginForm.command,
          args: pluginForm.args ? pluginForm.args.split(' ') : [],
          agent_id: agentId || undefined,
        });
      } else if (pluginType === 'skill') {
        await api.registerSkill({
          name: pluginForm.name,
          description: pluginForm.description || '',
          module_path: pluginForm.module_path,
          function_name: pluginForm.function_name,
          agent_id: agentId || undefined,
        });
      } else if (pluginType === 'rag') {
        await api.registerRAG({
          name: pluginForm.name,
          type: pluginForm.rag_type || 'vector_db',
          connection_string: pluginForm.connection_string,
          agent_id: agentId || undefined,
        });
      }
      setPluginModalVisible(false);
      loadPlugins();
      alert('Plugin registered successfully');
    } catch (error) {
      alert('Failed to register plugin');
    }
  };

  const handleDeletePlugin = async (pluginId: string) => {
    if (!confirm('Delete this plugin?')) return;
    try {
      await api.removePlugin(pluginId);
      loadPlugins();
    } catch (error) {
      alert('Failed to delete plugin');
    }
  };

  // Test agent
  const handleTest = async () => {
    if (!workflowId || !agentId || !testMessage.trim()) return;

    const userMessage = testMessage.trim();
    setTestMessage('');
    setTestLoading(true);

    // Add user message to chat
    setChatMessages(prev => [...prev, { role: 'user', content: userMessage }]);

    try {
      const result = await api.testAgent(workflowId, agentId, userMessage);
      let assistantContent = '';

      if (result.response?.messages && result.response.messages.length > 0) {
        assistantContent = result.response.messages.map((m: any) => m.content).join('\n');
      } else if (result.error) {
        assistantContent = `Error: ${result.error}`;
      } else {
        assistantContent = 'No response received';
      }

      // Add assistant message to chat
      setChatMessages(prev => [...prev, { role: 'assistant', content: assistantContent }]);
    } catch (error: any) {
      setChatMessages(prev => [...prev, { role: 'assistant', content: `Error: ${error.message || 'Unknown error'}` }]);
    } finally {
      setTestLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleTest();
    }
  };

  const clearChat = () => {
    setChatMessages([]);
  };

  const tabs = ['Basic', 'Model', 'Prompts', 'Tools', 'Output', 'Settings'];

  if (agentType !== 'builtin') {
    return (
      <div className={`${styles.drawer} ${visible ? styles.drawerVisible : ''}`}>
        <div className={styles.drawerHeader}><h3 className={styles.drawerTitle}>Agent Configuration</h3></div>
        <div className={styles.drawerBody}>
          <p>This agent type ({agentType}) uses external configuration.</p>
          <p>Please configure it through the corresponding platform.</p>
        </div>
        <div className={styles.drawerFooter}><button className={listStyles.button} onClick={onClose}>Close</button></div>
      </div>
    );
  }

  return (
    <>
      <div className={`${styles.drawer} ${visible ? styles.drawerVisible : ''}`}>
        <div className={styles.drawerHeader}>
          <h3 className={styles.drawerTitle}>Agent Editor</h3>
        </div>

        <div className={styles.drawerBody}>
          <nav className={styles.tabNav}>
            {tabs.map(tab => (
              <button
                key={tab}
                className={`${styles.tabButton} ${activeTab === tab.toLowerCase() ? styles.tabButtonActive : ''}`}
                onClick={() => setActiveTab(tab.toLowerCase())}>
                {tab}
              </button>
            ))}
          </nav>

          {loading ? (
            <p>Loading...</p>
          ) : (
            <form>
              {/* Basic Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'basic' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Agent Name</label>
                    <input name="name" value={formData.name || ''} onChange={handleFormChange} className={listStyles.formInput} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Description</label>
                    <textarea name="description" value={formData.description || ''} onChange={handleFormChange} className={listStyles.formTextarea} rows={3} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Category</label>
                    <select name="category" value={formData.category || 'general'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="general">General</option>
                      <option value="assistant">Assistant</option>
                      <option value="coding">Coding</option>
                      <option value="analysis">Analysis</option>
                      <option value="writing">Writing</option>
                      <option value="customer_service">Customer Service</option>
                      <option value="router">Router</option>
                    </select>
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Avatar URL</label>
                    <input name="avatar" value={formData.avatar || ''} onChange={handleFormChange} className={listStyles.formInput} placeholder="https://..." />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Tags (comma separated)</label>
                    <input
                      name="tags"
                      value={(formData.tags || []).join(', ')}
                      onChange={(e) => setFormData(prev => ({ ...prev, tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean) }))}
                      className={listStyles.formInput}
                      placeholder="tag1, tag2, tag3"
                    />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Version</label>
                    <input name="version" value={formData.version || '1.0.0'} onChange={handleFormChange} className={listStyles.formInput} />
                  </div>
                </div>
              </div>

              {/* Model Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'model' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Provider</label>
                    <select name="provider" value={formData.provider || 'openai'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="openai">OpenAI</option>
                      <option value="azure">Azure OpenAI</option>
                      <option value="anthropic">Anthropic</option>
                      <option value="zhipu">智谱 (Zhipu/GLM)</option>
                      <option value="deepseek">DeepSeek</option>
                      <option value="qwen">通义千问 (Qwen)</option>
                      <option value="moonshot">Moonshot (Kimi)</option>
                      <option value="yi">零一万物 (Yi)</option>
                      <option value="baichuan">百川 (Baichuan)</option>
                      <option value="ollama">Ollama (Local)</option>
                    </select>
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Model</label>
                    <input name="model" value={formData.model || 'gpt-4'} onChange={handleFormChange} className={listStyles.formInput} placeholder="gpt-4, claude-3-opus, etc." />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Base URL</label>
                    <input
                      name="base_url"
                      value={formData.base_url || ''}
                      onChange={handleFormChange}
                      className={listStyles.formInput}
                      placeholder={
                        formData.provider === 'openai' ? 'https://api.openai.com/v1' :
                        formData.provider === 'anthropic' ? 'https://api.anthropic.com' :
                        formData.provider === 'zhipu' ? 'https://open.bigmodel.cn/api/paas/v4' :
                        formData.provider === 'deepseek' ? 'https://api.deepseek.com' :
                        formData.provider === 'qwen' ? 'https://dashscope.aliyuncs.com/compatible-mode/v1' :
                        formData.provider === 'moonshot' ? 'https://api.moonshot.cn/v1' :
                        formData.provider === 'yi' ? 'https://api.lingyiwanwu.com/v1' :
                        formData.provider === 'baichuan' ? 'https://api.baichuan-ai.com/v1' :
                        formData.provider === 'ollama' ? 'http://localhost:11434/v1' :
                        'https://api.example.com/v1'
                      }
                    />
                    <small style={{ color: '#666' }}>Leave empty to use provider default</small>
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>API Key</label>
                    <input
                      name="api_key"
                      type="password"
                      value={formData.api_key || ''}
                      onChange={handleFormChange}
                      className={listStyles.formInput}
                      placeholder="sk-..."
                      autoComplete="off"
                    />
                    <small style={{ color: '#666' }}>Leave empty to use environment variable</small>
                  </div>
                </div>

                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>Parameters</h4>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Temperature ({formData.temperature || 0.7})</label>
                    <input type="range" name="temperature" min="0" max="2" step="0.1" value={formData.temperature || 0.7} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Max Tokens</label>
                    <input type="number" name="max_tokens" value={formData.max_tokens || 4096} onChange={handleFormChange} className={listStyles.formInput} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Top P ({formData.top_p || 1.0})</label>
                    <input type="range" name="top_p" min="0" max="1" step="0.1" value={formData.top_p || 1.0} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Frequency Penalty ({formData.frequency_penalty || 0})</label>
                    <input type="range" name="frequency_penalty" min="-2" max="2" step="0.1" value={formData.frequency_penalty || 0} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Presence Penalty ({formData.presence_penalty || 0})</label>
                    <input type="range" name="presence_penalty" min="-2" max="2" step="0.1" value={formData.presence_penalty || 0} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                </div>
              </div>

              {/* Prompts Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'prompts' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>System Prompt</label>
                    <textarea
                      name="system_prompt"
                      value={formData.system_prompt || ''}
                      onChange={handleFormChange}
                      className={listStyles.formTextarea}
                      rows={10}
                      placeholder="You are a helpful assistant..."
                    />
                  </div>
                </div>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Task Prompt Template</label>
                    <textarea
                      name="task_prompt_template"
                      value={formData.task_prompt_template || ''}
                      onChange={handleFormChange}
                      className={listStyles.formTextarea}
                      rows={5}
                      placeholder="Use {{input}} for user input placeholder"
                    />
                    <small style={{ color: '#888' }}>Use {'{{input}}'} to reference user input</small>
                  </div>
                </div>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Output Instructions</label>
                    <textarea
                      name="output_instructions"
                      value={formData.output_instructions || ''}
                      onChange={handleFormChange}
                      className={listStyles.formTextarea}
                      rows={4}
                      placeholder="Instructions for how the agent should format its output..."
                    />
                  </div>
                </div>
              </div>

              {/* Tools Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'tools' ? styles.tabContentActive : ''}`}>
                {/* Smart warning: detect tools mentioned in prompts but not enabled */}
                {(() => {
                  const allToolNames = Object.values(systemTools).flat().map(t => t.name);
                  const prompt = `${formData.system_prompt || ''} ${formData.task_prompt_template || ''} ${formData.output_instructions || ''}`;
                  const mentionedButNotEnabled = allToolNames.filter(
                    name => prompt.includes(name) && !(formData.system_tools || []).includes(name)
                  );
                  if (mentionedButNotEnabled.length === 0) return null;
                  return (
                    <div style={{
                      padding: '12px 16px',
                      background: 'rgba(237, 137, 54, 0.15)',
                      border: '1px solid rgba(237, 137, 54, 0.4)',
                      borderRadius: '8px',
                      marginBottom: '16px',
                      fontSize: '0.85rem',
                    }}>
                      <strong style={{ color: '#ed8936' }}>Prompt mentions unused tools</strong>
                      <p style={{ margin: '6px 0 8px', color: '#ccc' }}>
                        Your prompt references the following tools, but they are not enabled. The agent will not be able to call them:
                      </p>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        {mentionedButNotEnabled.map(name => (
                          <button
                            key={name}
                            type="button"
                            onClick={() => {
                              setFormData(prev => ({
                                ...prev,
                                system_tools: [...(prev.system_tools || []), name],
                              }));
                            }}
                            style={{
                              padding: '4px 12px',
                              background: 'rgba(237, 137, 54, 0.3)',
                              border: '1px solid #ed8936',
                              borderRadius: '4px',
                              color: '#fff',
                              cursor: 'pointer',
                              fontSize: '0.85rem',
                            }}
                          >
                            + Enable {name}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })()}

                {/* System Tools Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>System Tools</h4>
                    <span style={{ fontSize: '0.8rem', color: '#888' }}>
                      {(formData.system_tools || []).length} enabled
                    </span>
                  </div>
                  <p style={{ color: '#888', fontSize: '0.85rem', marginBottom: '12px' }}>
                    Select built-in system tools to enable for this agent (file operations, shell commands, web access, etc.)
                  </p>

                  {systemToolCategories.map((category) => (
                    <div key={category} style={{ marginBottom: '16px' }}>
                      <h5 style={{ margin: '0 0 8px 0', textTransform: 'capitalize', color: '#aaa', fontSize: '0.9rem' }}>
                        {category === 'filesystem' ? '📁 File System' :
                         category === 'shell' ? '🖥️ Shell' :
                         category === 'web' ? '🌐 Web' :
                         category}
                      </h5>
                      <div style={{ display: 'grid', gap: '8px' }}>
                        {(systemTools[category] || []).map((tool) => {
                          const isEnabled = (formData.system_tools || []).includes(tool.name);
                          return (
                            <div
                              key={tool.name}
                              className={styles.toolCard}
                              style={{
                                cursor: 'pointer',
                                border: isEnabled ? '1px solid var(--color-cta, #6366f1)' : '1px solid transparent',
                                background: isEnabled ? 'rgba(99, 102, 241, 0.1)' : undefined,
                              }}
                              onClick={() => {
                                const current = formData.system_tools || [];
                                const newTools = isEnabled
                                  ? current.filter((t: string) => t !== tool.name)
                                  : [...current, tool.name];
                                setFormData(prev => ({ ...prev, system_tools: newTools }));
                              }}
                            >
                              <div className={styles.toolHeader}>
                                <div className={styles.toolTitle}>
                                  <input
                                    type="checkbox"
                                    checked={isEnabled}
                                    onChange={() => {}}
                                    style={{ marginRight: '8px' }}
                                  />
                                  <span>{tool.name}</span>
                                  {tool.is_dangerous && (
                                    <span style={{ fontSize: '0.7rem', padding: '2px 6px', background: '#e53e3e', borderRadius: '4px', marginLeft: '8px' }}>
                                      Dangerous
                                    </span>
                                  )}
                                  {tool.requires_approval && (
                                    <span style={{ fontSize: '0.7rem', padding: '2px 6px', background: '#d69e2e', borderRadius: '4px', marginLeft: '8px' }}>
                                      Approval
                                    </span>
                                  )}
                                </div>
                              </div>
                              <p className={styles.toolDescription}>{tool.description}</p>
                              {tool.parameters && tool.parameters.length > 0 && (
                                <div style={{ marginTop: '4px', fontSize: '0.75rem', color: '#666' }}>
                                  Params: {tool.parameters.map(p => p.name).join(', ')}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}

                  {systemToolCategories.length === 0 && (
                    <p style={{ color: '#888' }}>Loading system tools...</p>
                  )}
                </div>

                <hr className={styles.divider} />

                {/* Built-in Tools Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>Built-in Tools</h4>
                    <button type="button" className={listStyles.button} onClick={handleAddTool}>+ Add Tool</button>
                  </div>

                  {(formData.builtin_tools || []).length === 0 ? (
                    <p style={{ color: '#888' }}>No tools configured</p>
                  ) : (
                    (formData.builtin_tools || []).map((tool, index) => (
                      <div key={index} className={styles.toolCard}>
                        <div className={styles.toolHeader}>
                          <div className={styles.toolTitle}>
                            <span>{tool.name}</span>
                            <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: '#333', borderRadius: '4px' }}>
                              {tool.tool_type}
                            </span>
                          </div>
                          <div>
                            <button type="button" className={listStyles.buttonLink} onClick={() => handleEditTool(tool)}>Edit</button>
                            <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeleteTool(tool.name)}>Delete</button>
                          </div>
                        </div>
                        <p className={styles.toolDescription}>{tool.description}</p>
                        {tool.parameters && tool.parameters.length > 0 && (
                          <div style={{ marginTop: '8px', fontSize: '0.8rem', color: '#888' }}>
                            Parameters: {tool.parameters.map(p => p.name).join(', ')}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <hr className={styles.divider} />

                {/* MCP Servers Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>MCP Servers</h4>
                    <button type="button" className={listStyles.button} onClick={() => handleAddPlugin('mcp')}>+ Add MCP</button>
                  </div>

                  {plugins.filter(p => p.type === 'mcp').length === 0 ? (
                    <p style={{ color: '#888' }}>No MCP servers configured</p>
                  ) : (
                    plugins.filter(p => p.type === 'mcp').map((plugin) => (
                      <div key={plugin.id} className={styles.toolCard}>
                        <div className={styles.toolHeader}>
                          <div className={styles.toolTitle}>
                            <span>{plugin.name}</span>
                            <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: '#2d3748', borderRadius: '4px' }}>MCP</span>
                          </div>
                          <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeletePlugin(plugin.id)}>Delete</button>
                        </div>
                        {plugin.tools && plugin.tools.length > 0 && (
                          <p className={styles.toolDescription}>Tools: {plugin.tools.join(', ')}</p>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <hr className={styles.divider} />

                {/* Skills Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>Skills</h4>
                    <button type="button" className={listStyles.button} onClick={() => handleAddPlugin('skill')}>+ Add Skill</button>
                  </div>

                  {plugins.filter(p => p.type === 'skill').length === 0 ? (
                    <p style={{ color: '#888' }}>No skills configured</p>
                  ) : (
                    plugins.filter(p => p.type === 'skill').map((plugin) => (
                      <div key={plugin.id} className={styles.toolCard}>
                        <div className={styles.toolHeader}>
                          <div className={styles.toolTitle}>
                            <span>{plugin.name}</span>
                            <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: '#553c9a', borderRadius: '4px' }}>Skill</span>
                          </div>
                          <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeletePlugin(plugin.id)}>Delete</button>
                        </div>
                        {plugin.tools && plugin.tools.length > 0 && (
                          <p className={styles.toolDescription}>Functions: {plugin.tools.join(', ')}</p>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <hr className={styles.divider} />

                {/* RAG Sources Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>RAG Sources</h4>
                    <button type="button" className={listStyles.button} onClick={() => handleAddPlugin('rag')}>+ Add RAG</button>
                  </div>

                  {plugins.filter(p => p.type === 'rag').length === 0 ? (
                    <p style={{ color: '#888' }}>No RAG sources configured</p>
                  ) : (
                    plugins.filter(p => p.type === 'rag').map((plugin) => (
                      <div key={plugin.id} className={styles.toolCard}>
                        <div className={styles.toolHeader}>
                          <div className={styles.toolTitle}>
                            <span>{plugin.name}</span>
                            <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: '#2f855a', borderRadius: '4px' }}>RAG</span>
                          </div>
                          <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeletePlugin(plugin.id)}>Delete</button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Output Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'output' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Output Format Type</label>
                    <select
                      value={formData.output_format?.format_type || 'text'}
                      onChange={(e) => setFormData(prev => ({
                        ...prev,
                        output_format: { ...prev.output_format, format_type: e.target.value as any }
                      }))}
                      className={listStyles.formInput}
                    >
                      <option value="text">Plain Text</option>
                      <option value="markdown">Markdown</option>
                      <option value="json">JSON</option>
                      <option value="structured">Structured</option>
                    </select>
                  </div>

                  {formData.output_format?.format_type === 'json' && (
                    <div className={listStyles.formGroup}>
                      <label className={listStyles.formLabel}>JSON Schema</label>
                      <textarea
                        value={JSON.stringify(formData.output_format?.json_schema || {}, null, 2)}
                        onChange={(e) => {
                          try {
                            const schema = JSON.parse(e.target.value);
                            setFormData(prev => ({
                              ...prev,
                              output_format: { ...prev.output_format, json_schema: schema }
                            }));
                          } catch {}
                        }}
                        className={listStyles.formTextarea}
                        rows={8}
                        placeholder='{"type": "object", "properties": {...}}'
                      />
                    </div>
                  )}

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Output Example</label>
                    <textarea
                      value={formData.output_format?.example || ''}
                      onChange={(e) => setFormData(prev => ({
                        ...prev,
                        output_format: { ...prev.output_format, example: e.target.value }
                      }))}
                      className={listStyles.formTextarea}
                      rows={4}
                      placeholder="Example of expected output..."
                    />
                  </div>
                </div>

                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Max Output Tokens</label>
                    <input
                      type="number"
                      name="max_output_tokens"
                      value={formData.max_output_tokens || 4096}
                      onChange={handleFormChange}
                      className={listStyles.formInput}
                    />
                  </div>
                </div>
              </div>

              {/* Settings Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'settings' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>Routing Strategy</h4>
                  <p style={{ color: '#888', fontSize: '0.85rem', marginBottom: '12px' }}>
                    How this agent routes tasks to its child agents (only applies if this agent has children)
                  </p>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Routing Mode</label>
                    <select name="routing_strategy" value={formData.routing_strategy || 'sequential'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="sequential">Sequential - Execute children one by one</option>
                      <option value="parallel">Parallel - Execute all children simultaneously</option>
                      <option value="conditional">Conditional - Route based on conditions</option>
                      <option value="handoff">Handoff - Transfer control to specialist</option>
                      <option value="hierarchical">Hierarchical - Decompose and aggregate</option>
                      <option value="coordinator">Coordinator - Parent integrates child results</option>
                      <option value="round_robin">Round Robin - Distribute evenly</option>
                      <option value="load_balanced">Load Balanced - Based on agent load</option>
                    </select>
                  </div>

                  {/* Strategy-specific tips */}
                  {formData.routing_strategy === 'sequential' && (
                    <div style={{ padding: '12px', background: 'rgba(99, 102, 241, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#6366f1' }}>Sequential Mode</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        Children execute one by one. Each child receives the accumulated context from previous children.
                        Best for: pipelines, step-by-step processing, dependent tasks.
                      </p>
                    </div>
                  )}

                  {formData.routing_strategy === 'parallel' && (
                    <div style={{ padding: '12px', background: 'rgba(34, 197, 94, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#22c55e' }}>Parallel Mode</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        All children execute simultaneously. Results are collected when all complete.
                        Best for: independent subtasks, faster execution, batch processing.
                      </p>
                    </div>
                  )}

                  {(formData.routing_strategy === 'conditional' || formData.routing_strategy === 'handoff') && (
                    <div style={{ padding: '12px', background: 'rgba(251, 191, 36, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#fbbf24' }}>Conditional/Handoff Mode</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        Routes to specific child based on parent's output content. Configure conditions to match keywords.
                        Best for: classification, intent routing, specialist delegation.
                      </p>
                      <p style={{ margin: '8px 0 0', fontSize: '0.8rem', color: '#888' }}>
                        Tip: Use parent's system prompt to output specific keywords that match routing conditions.
                      </p>
                    </div>
                  )}

                  {formData.routing_strategy === 'coordinator' && (
                    <div style={{ padding: '12px', background: 'rgba(168, 85, 247, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#a855f7' }}>Coordinator Mode</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        Parent sends task to children, then receives their responses and synthesizes a final answer.
                        Best for: multi-expert collaboration, consensus building, comprehensive analysis.
                      </p>
                    </div>
                  )}

                  {formData.routing_strategy === 'hierarchical' && (
                    <div style={{ padding: '12px', background: 'rgba(236, 72, 153, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#ec4899' }}>Hierarchical Mode</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        Parent decomposes the task, distributes subtasks to children, and aggregates results.
                        Best for: complex task decomposition, divide-and-conquer strategies.
                      </p>
                    </div>
                  )}
                </div>

                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>Execution Settings</h4>

                  <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <input
                      type="checkbox"
                      name="streaming_enabled"
                      checked={formData.streaming_enabled !== false}
                      onChange={handleFormChange}
                      id="streaming_enabled"
                    />
                    <label htmlFor="streaming_enabled">Enable Streaming</label>
                  </div>

                  <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <input
                      type="checkbox"
                      name="parallel_tool_calls"
                      checked={formData.parallel_tool_calls !== false}
                      onChange={handleFormChange}
                      id="parallel_tool_calls"
                    />
                    <label htmlFor="parallel_tool_calls">Allow Parallel Tool Calls</label>
                  </div>

                  <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <input
                      type="checkbox"
                      name="content_filter_enabled"
                      checked={formData.content_filter_enabled !== false}
                      onChange={handleFormChange}
                      id="content_filter_enabled"
                    />
                    <label htmlFor="content_filter_enabled">Enable Content Filter</label>
                  </div>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Tool Choice</label>
                    <select name="tool_choice" value={formData.tool_choice || 'auto'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="auto">Auto</option>
                      <option value="none">None</option>
                      <option value="required">Required</option>
                    </select>
                  </div>
                </div>

                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>Context Management</h4>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Context Window Strategy</label>
                    <select name="context_window_strategy" value={formData.context_window_strategy || 'sliding'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="sliding">Sliding Window</option>
                      <option value="truncate">Truncate Old</option>
                      <option value="summarize">Summarize</option>
                      <option value="smart">Smart Selection</option>
                    </select>
                  </div>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Max Context Messages</label>
                    <input
                      type="number"
                      name="max_context_messages"
                      value={formData.max_context_messages || 20}
                      onChange={handleFormChange}
                      className={listStyles.formInput}
                    />
                  </div>
                </div>

                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>Knowledge Base</h4>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Knowledge Base ID</label>
                    <input
                      name="knowledge_base"
                      value={formData.knowledge_base || ''}
                      onChange={handleFormChange}
                      className={listStyles.formInput}
                      placeholder="Optional knowledge base reference"
                    />
                  </div>
                </div>
              </div>
            </form>
          )}
        </div>

        <div className={styles.drawerFooter}>
          <button className={listStyles.buttonLink} onClick={onClose}>Cancel</button>
          <button className={listStyles.button} onClick={() => setTestModalVisible(true)}>Test</button>
          <button className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSave} disabled={loading}>
            {loading ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {/* Test Modal - Chat Interface */}
      <Modal isOpen={testModalVisible} onClose={() => setTestModalVisible(false)} title={`Chat with ${formData.name || 'Agent'}`}>
        <div style={{ display: 'flex', flexDirection: 'column', height: '500px' }}>
          {/* Chat Messages Area */}
          <div
            ref={chatContainerRef}
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '12px',
              background: '#0d0d1a',
              borderRadius: '8px',
              marginBottom: '12px',
            }}
          >
            {chatMessages.length === 0 ? (
              <div style={{ color: '#666', textAlign: 'center', marginTop: '50px' }}>
                <p>Start a conversation with the agent</p>
                <p style={{ fontSize: '0.8rem' }}>Type a message below and press Enter or click Send</p>
              </div>
            ) : (
              chatMessages.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    marginBottom: '12px',
                  }}
                >
                  <div
                    style={{
                      maxWidth: '80%',
                      padding: '10px 14px',
                      borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                      background: msg.role === 'user' ? 'var(--color-cta, #6366f1)' : '#1e1e3f',
                      color: '#fff',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      fontSize: '0.9rem',
                      lineHeight: '1.5',
                    }}
                  >
                    {msg.role === 'assistant' && (
                      <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '4px' }}>
                        🤖 {formData.name || 'Agent'}
                      </div>
                    )}
                    {msg.content}
                  </div>
                </div>
              ))
            )}
            {testLoading && (
              <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '12px' }}>
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '16px 16px 16px 4px',
                  background: '#1e1e3f',
                  color: '#888',
                }}>
                  <span className={styles.thinkingIndicator}>Thinking...</span>
                </div>
              </div>
            )}
          </div>

          {/* Input Area */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <textarea
              value={testMessage}
              onChange={(e) => setTestMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              className={listStyles.formTextarea}
              style={{ flex: 1, resize: 'none' }}
              rows={2}
              placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
              disabled={testLoading}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <button
                type="button"
                className={`${listStyles.button} ${listStyles.buttonPrimary}`}
                onClick={handleTest}
                disabled={testLoading || !testMessage.trim()}
                style={{ flex: 1 }}
              >
                {testLoading ? '...' : 'Send'}
              </button>
              <button
                type="button"
                className={listStyles.button}
                onClick={clearChat}
                disabled={testLoading || chatMessages.length === 0}
                style={{ flex: 1, fontSize: '0.8rem' }}
              >
                Clear
              </button>
            </div>
          </div>
        </div>

        <div className={listStyles.modalFooter} style={{ marginTop: '12px' }}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setTestModalVisible(false)}>Close</button>
        </div>
      </Modal>

      {/* Tool Modal */}
      <Modal isOpen={toolModalVisible} onClose={() => setToolModalVisible(false)} title={editingTool ? 'Edit Tool' : 'Add Tool'}>
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Tool Name</label>
          <input
            value={toolForm.name || ''}
            onChange={(e) => setToolForm(prev => ({ ...prev, name: e.target.value }))}
            className={listStyles.formInput}
            placeholder="my_tool"
          />
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Description</label>
          <textarea
            value={toolForm.description || ''}
            onChange={(e) => setToolForm(prev => ({ ...prev, description: e.target.value }))}
            className={listStyles.formTextarea}
            rows={2}
            placeholder="What this tool does..."
          />
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Tool Type</label>
          <select
            value={toolForm.tool_type || 'http'}
            onChange={(e) => setToolForm(prev => ({ ...prev, tool_type: e.target.value as any }))}
            className={listStyles.formInput}
          >
            <option value="http">HTTP Request</option>
            <option value="code">Code Execution</option>
            <option value="transform">Data Transform</option>
          </select>
        </div>

        {toolForm.tool_type === 'http' && (
          <>
            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>HTTP Method</label>
              <select
                value={toolForm.http_method || 'GET'}
                onChange={(e) => setToolForm(prev => ({ ...prev, http_method: e.target.value }))}
                className={listStyles.formInput}
              >
                <option value="GET">GET</option>
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="DELETE">DELETE</option>
                <option value="PATCH">PATCH</option>
              </select>
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>URL</label>
              <input
                value={toolForm.http_url || ''}
                onChange={(e) => setToolForm(prev => ({ ...prev, http_url: e.target.value }))}
                className={listStyles.formInput}
                placeholder="https://api.example.com/endpoint"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Headers (JSON)</label>
              <textarea
                value={JSON.stringify(toolForm.http_headers || {}, null, 2)}
                onChange={(e) => {
                  try {
                    const headers = JSON.parse(e.target.value);
                    setToolForm(prev => ({ ...prev, http_headers: headers }));
                  } catch {}
                }}
                className={listStyles.formTextarea}
                rows={3}
                placeholder='{"Authorization": "Bearer {{token}}"}'
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Body Template (JSON)</label>
              <textarea
                value={toolForm.http_body_template || ''}
                onChange={(e) => setToolForm(prev => ({ ...prev, http_body_template: e.target.value }))}
                className={listStyles.formTextarea}
                rows={3}
                placeholder='{"query": "{{param_name}}"}'
              />
            </div>
          </>
        )}

        {toolForm.tool_type === 'code' && (
          <>
            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Language</label>
              <select
                value={toolForm.code_language || 'python'}
                onChange={(e) => setToolForm(prev => ({ ...prev, code_language: e.target.value }))}
                className={listStyles.formInput}
              >
                <option value="python">Python</option>
                <option value="javascript">JavaScript</option>
              </select>
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Code</label>
              <textarea
                value={toolForm.code || ''}
                onChange={(e) => setToolForm(prev => ({ ...prev, code: e.target.value }))}
                className={listStyles.formTextarea}
                rows={8}
                style={{ fontFamily: 'monospace' }}
                placeholder="def execute(params):\n    return result"
              />
            </div>
          </>
        )}

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Timeout (seconds)</label>
          <input
            type="number"
            value={toolForm.timeout || 30}
            onChange={(e) => setToolForm(prev => ({ ...prev, timeout: parseInt(e.target.value) || 30 }))}
            className={listStyles.formInput}
          />
        </div>

        <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <input
            type="checkbox"
            checked={toolForm.approval_required || false}
            onChange={(e) => setToolForm(prev => ({ ...prev, approval_required: e.target.checked }))}
            id="approval_required"
          />
          <label htmlFor="approval_required">Require Approval Before Execution</label>
        </div>

        {/* Parameters Section */}
        <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #333' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <label className={listStyles.formLabel} style={{ margin: 0 }}>Parameters</label>
            <button type="button" className={listStyles.buttonLink} onClick={handleAddParameter}>+ Add Parameter</button>
          </div>

          {(toolForm.parameters || []).map((param, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', padding: '8px', background: '#1a1a2e', borderRadius: '4px' }}>
              <span style={{ flex: 1 }}>{param.name} ({param.type}){param.required && ' *'}</span>
              <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeleteParameter(param.name)}>Remove</button>
            </div>
          ))}
        </div>

        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setToolModalVisible(false)}>Cancel</button>
          <button type="button" className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSaveTool}>
            {editingTool ? 'Update Tool' : 'Add Tool'}
          </button>
        </div>
      </Modal>

      {/* Parameter Modal */}
      <Modal isOpen={paramModalVisible} onClose={() => setParamModalVisible(false)} title="Add Parameter">
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Parameter Name</label>
          <input
            value={paramForm.name || ''}
            onChange={(e) => setParamForm(prev => ({ ...prev, name: e.target.value }))}
            className={listStyles.formInput}
            placeholder="param_name"
          />
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Type</label>
          <select
            value={paramForm.type || 'string'}
            onChange={(e) => setParamForm(prev => ({ ...prev, type: e.target.value as any }))}
            className={listStyles.formInput}
          >
            <option value="string">String</option>
            <option value="integer">Integer</option>
            <option value="number">Number</option>
            <option value="boolean">Boolean</option>
            <option value="array">Array</option>
            <option value="object">Object</option>
          </select>
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>Description</label>
          <input
            value={paramForm.description || ''}
            onChange={(e) => setParamForm(prev => ({ ...prev, description: e.target.value }))}
            className={listStyles.formInput}
            placeholder="Parameter description"
          />
        </div>

        <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <input
            type="checkbox"
            checked={paramForm.required || false}
            onChange={(e) => setParamForm(prev => ({ ...prev, required: e.target.checked }))}
            id="param_required"
          />
          <label htmlFor="param_required">Required</label>
        </div>

        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setParamModalVisible(false)}>Cancel</button>
          <button type="button" className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSaveParameter}>Add</button>
        </div>
      </Modal>

      {/* Plugin Modal */}
      <Modal isOpen={pluginModalVisible} onClose={() => setPluginModalVisible(false)} title={`Add ${pluginType.toUpperCase()}`}>
        {pluginType === 'mcp' && (
          <>
            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Name</label>
              <input
                value={pluginForm.name || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, name: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my-mcp-server"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Command</label>
              <input
                value={pluginForm.command || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, command: e.target.value }))}
                className={listStyles.formInput}
                placeholder="npx -y @modelcontextprotocol/server-xxx"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Arguments (space separated)</label>
              <input
                value={pluginForm.args || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, args: e.target.value }))}
                className={listStyles.formInput}
                placeholder="--port 3000"
              />
            </div>
          </>
        )}

        {pluginType === 'skill' && (
          <>
            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Name</label>
              <input
                value={pluginForm.name || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, name: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my_skill"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Description</label>
              <textarea
                value={pluginForm.description || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, description: e.target.value }))}
                className={listStyles.formTextarea}
                rows={2}
                placeholder="What this skill does..."
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Module Path</label>
              <input
                value={pluginForm.module_path || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, module_path: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my_module.skills"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Function Name</label>
              <input
                value={pluginForm.function_name || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, function_name: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my_function"
              />
            </div>
          </>
        )}

        {pluginType === 'rag' && (
          <>
            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Name</label>
              <input
                value={pluginForm.name || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, name: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my_knowledge_base"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>RAG Type</label>
              <select
                value={pluginForm.rag_type || 'vector_db'}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, rag_type: e.target.value }))}
                className={listStyles.formInput}
              >
                <option value="vector_db">Vector Database</option>
                <option value="elasticsearch">Elasticsearch</option>
                <option value="pinecone">Pinecone</option>
                <option value="chroma">Chroma</option>
                <option value="qdrant">Qdrant</option>
              </select>
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>Connection String</label>
              <input
                value={pluginForm.connection_string || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, connection_string: e.target.value }))}
                className={listStyles.formInput}
                placeholder="http://localhost:6333"
              />
            </div>
          </>
        )}

        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setPluginModalVisible(false)}>Cancel</button>
          <button type="button" className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSavePlugin}>
            Register
          </button>
        </div>
      </Modal>
    </>
  );
};

export default AgentEditor;
