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

  const tabs = ['基本', '模型', '提示词', '工具', '输出', '设置'];

  if (agentType !== 'builtin') {
    return (
      <div className={`${styles.drawer} ${visible ? styles.drawerVisible : ''}`}>
        <div className={styles.drawerHeader}><h3 className={styles.drawerTitle}>Agent 配置</h3></div>
        <div className={styles.drawerBody}>
          <p>此 Agent 类型 ({agentType}) 使用外部配置。</p>
          <p>请通过对应平台进行配置。</p>
        </div>
        <div className={styles.drawerFooter}><button className={listStyles.button} onClick={onClose}>关闭</button></div>
      </div>
    );
  }

  return (
    <>
      <div className={`${styles.drawer} ${visible ? styles.drawerVisible : ''}`}>
        <div className={styles.drawerHeader}>
          <h3 className={styles.drawerTitle}>Agent 编辑器</h3>
        </div>

        <div className={styles.drawerBody}>
          <nav className={styles.tabNav}>
            {tabs.map(tab => (
              <button
                key={tab}
                className={`${styles.tabButton} ${activeTab === ['基本', '模型', '提示词', '工具', '输出', '设置'].indexOf(tab) === ['basic', 'model', 'prompts', 'tools', 'output', 'settings'].indexOf(activeTab) ? styles.tabButtonActive : ''}`}
                onClick={() => setActiveTab(['basic', 'model', 'prompts', 'tools', 'output', 'settings'][['基本', '模型', '提示词', '工具', '输出', '设置'].indexOf(tab)])}>
                {tab}
              </button>
            ))}
          </nav>

          {loading ? (
            <p>加载中...</p>
          ) : (
            <form>
              {/* Basic Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'basic' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Agent 名称</label>
                    <input name="name" value={formData.name || ''} onChange={handleFormChange} className={listStyles.formInput} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>描述</label>
                    <textarea name="description" value={formData.description || ''} onChange={handleFormChange} className={listStyles.formTextarea} rows={3} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>分类</label>
                    <select name="category" value={formData.category || 'general'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="general">通用</option>
                      <option value="assistant">助手</option>
                      <option value="coding">编程</option>
                      <option value="analysis">分析</option>
                      <option value="writing">写作</option>
                      <option value="customer_service">客服</option>
                      <option value="router">路由</option>
                    </select>
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>头像 URL</label>
                    <input name="avatar" value={formData.avatar || ''} onChange={handleFormChange} className={listStyles.formInput} placeholder="https://..." />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>标签 (逗号分隔)</label>
                    <input
                      name="tags"
                      value={(formData.tags || []).join(', ')}
                      onChange={(e) => setFormData(prev => ({ ...prev, tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean) }))}
                      className={listStyles.formInput}
                      placeholder="标签1, 标签2, 标签3"
                    />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>版本</label>
                    <input name="version" value={formData.version || '1.0.0'} onChange={handleFormChange} className={listStyles.formInput} />
                  </div>
                </div>
              </div>

              {/* Model Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'model' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>服务商</label>
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
                      <option value="ollama">Ollama (本地)</option>
                    </select>
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>模型</label>
                    <input name="model" value={formData.model || 'gpt-4'} onChange={handleFormChange} className={listStyles.formInput} placeholder="gpt-4, claude-3-opus, etc." />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>API 地址</label>
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
                    <small style={{ color: '#666' }}>留空使用服务商默认地址</small>
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
                    <small style={{ color: '#666' }}>留空使用环境变量</small>
                  </div>
                </div>

                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>参数设置</h4>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>温度 ({formData.temperature || 0.7})</label>
                    <input type="range" name="temperature" min="0" max="2" step="0.1" value={formData.temperature || 0.7} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>最大 Token 数</label>
                    <input type="number" name="max_tokens" value={formData.max_tokens || 4096} onChange={handleFormChange} className={listStyles.formInput} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>Top P ({formData.top_p || 1.0})</label>
                    <input type="range" name="top_p" min="0" max="1" step="0.1" value={formData.top_p || 1.0} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>频率惩罚 ({formData.frequency_penalty || 0})</label>
                    <input type="range" name="frequency_penalty" min="-2" max="2" step="0.1" value={formData.frequency_penalty || 0} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>存在惩罚 ({formData.presence_penalty || 0})</label>
                    <input type="range" name="presence_penalty" min="-2" max="2" step="0.1" value={formData.presence_penalty || 0} onChange={handleFormChange} style={{ width: '100%' }} />
                  </div>
                </div>
              </div>

              {/* Prompts Tab */}
              <div className={`${styles.tabContent} ${activeTab === 'prompts' ? styles.tabContentActive : ''}`}>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>系统提示词</label>
                    <textarea
                      name="system_prompt"
                      value={formData.system_prompt || ''}
                      onChange={handleFormChange}
                      className={listStyles.formTextarea}
                      rows={10}
                      placeholder="你是一个有帮助的助手..."
                    />
                  </div>
                </div>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>任务提示词模板</label>
                    <textarea
                      name="task_prompt_template"
                      value={formData.task_prompt_template || ''}
                      onChange={handleFormChange}
                      className={listStyles.formTextarea}
                      rows={5}
                      placeholder="使用 {{input}} 作为用户输入占位符"
                    />
                    <small style={{ color: '#888' }}>使用 {'{{input}}'} 引用用户输入</small>
                  </div>
                </div>
                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>输出指令</label>
                    <textarea
                      name="output_instructions"
                      value={formData.output_instructions || ''}
                      onChange={handleFormChange}
                      className={listStyles.formTextarea}
                      rows={4}
                      placeholder="指定 Agent 输出格式的指令..."
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
                      <strong style={{ color: '#ed8936' }}>提示词中提到了未启用的工具</strong>
                      <p style={{ margin: '6px 0 8px', color: '#ccc' }}>
                        你的提示词引用了以下工具，但它们尚未启用。Agent 将无法调用这些工具:
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
                            + 启用 {name}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })()}

                {/* System Tools Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>系统工具</h4>
                    <span style={{ fontSize: '0.8rem', color: '#888' }}>
                      已启用 {(formData.system_tools || []).length} 个
                    </span>
                  </div>
                  <p style={{ color: '#888', fontSize: '0.85rem', marginBottom: '12px' }}>
                    选择要为此 Agent 启用的内置系统工具 (文件操作、Shell 命令、网络访问等)
                  </p>

                  {systemToolCategories.map((category) => (
                    <div key={category} style={{ marginBottom: '16px' }}>
                      <h5 style={{ margin: '0 0 8px 0', textTransform: 'capitalize', color: '#aaa', fontSize: '0.9rem' }}>
                        {category === 'filesystem' ? '📁 文件系统' :
                         category === 'shell' ? '🖥️ Shell' :
                         category === 'web' ? '🌐 网络' :
                         category === 'communication' ? '📧 通讯' :
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
                                      危险
                                    </span>
                                  )}
                                  {tool.requires_approval && (
                                    <span style={{ fontSize: '0.7rem', padding: '2px 6px', background: '#d69e2e', borderRadius: '4px', marginLeft: '8px' }}>
                                      需审批
                                    </span>
                                  )}
                                </div>
                              </div>
                              <p className={styles.toolDescription}>{tool.description}</p>
                              {tool.parameters && tool.parameters.length > 0 && (
                                <div style={{ marginTop: '4px', fontSize: '0.75rem', color: '#666' }}>
                                  参数: {tool.parameters.map(p => p.name).join(', ')}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}

                  {systemToolCategories.length === 0 && (
                    <p style={{ color: '#888' }}>加载系统工具中...</p>
                  )}
                </div>

                <hr className={styles.divider} />

                {/* Built-in Tools Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>自定义工具</h4>
                    <button type="button" className={listStyles.button} onClick={handleAddTool}>+ 添加工具</button>
                  </div>

                  {(formData.builtin_tools || []).length === 0 ? (
                    <p style={{ color: '#888' }}>暂无配置的工具</p>
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
                            <button type="button" className={listStyles.buttonLink} onClick={() => handleEditTool(tool)}>编辑</button>
                            <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeleteTool(tool.name)}>删除</button>
                          </div>
                        </div>
                        <p className={styles.toolDescription}>{tool.description}</p>
                        {tool.parameters && tool.parameters.length > 0 && (
                          <div style={{ marginTop: '8px', fontSize: '0.8rem', color: '#888' }}>
                            参数: {tool.parameters.map(p => p.name).join(', ')}
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
                    <h4 style={{ margin: 0 }}>MCP 服务器</h4>
                    <button type="button" className={listStyles.button} onClick={() => handleAddPlugin('mcp')}>+ 添加 MCP</button>
                  </div>

                  {plugins.filter(p => p.type === 'mcp').length === 0 ? (
                    <p style={{ color: '#888' }}>暂无配置的 MCP 服务器</p>
                  ) : (
                    plugins.filter(p => p.type === 'mcp').map((plugin) => (
                      <div key={plugin.id} className={styles.toolCard}>
                        <div className={styles.toolHeader}>
                          <div className={styles.toolTitle}>
                            <span>{plugin.name}</span>
                            <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: '#2d3748', borderRadius: '4px' }}>MCP</span>
                          </div>
                          <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeletePlugin(plugin.id)}>删除</button>
                        </div>
                        {plugin.tools && plugin.tools.length > 0 && (
                          <p className={styles.toolDescription}>工具: {plugin.tools.join(', ')}</p>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <hr className={styles.divider} />

                {/* Skills Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>技能</h4>
                    <button type="button" className={listStyles.button} onClick={() => handleAddPlugin('skill')}>+ 添加技能</button>
                  </div>

                  {plugins.filter(p => p.type === 'skill').length === 0 ? (
                    <p style={{ color: '#888' }}>暂无配置的技能</p>
                  ) : (
                    plugins.filter(p => p.type === 'skill').map((plugin) => (
                      <div key={plugin.id} className={styles.toolCard}>
                        <div className={styles.toolHeader}>
                          <div className={styles.toolTitle}>
                            <span>{plugin.name}</span>
                            <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: '#553c9a', borderRadius: '4px' }}>Skill</span>
                          </div>
                          <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeletePlugin(plugin.id)}>删除</button>
                        </div>
                        {plugin.tools && plugin.tools.length > 0 && (
                          <p className={styles.toolDescription}>函数: {plugin.tools.join(', ')}</p>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <hr className={styles.divider} />

                {/* RAG Sources Section */}
                <div className={styles.formSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h4 style={{ margin: 0 }}>RAG 数据源</h4>
                    <button type="button" className={listStyles.button} onClick={() => handleAddPlugin('rag')}>+ 添加 RAG</button>
                  </div>

                  {plugins.filter(p => p.type === 'rag').length === 0 ? (
                    <p style={{ color: '#888' }}>暂无配置的 RAG 数据源</p>
                  ) : (
                    plugins.filter(p => p.type === 'rag').map((plugin) => (
                      <div key={plugin.id} className={styles.toolCard}>
                        <div className={styles.toolHeader}>
                          <div className={styles.toolTitle}>
                            <span>{plugin.name}</span>
                            <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: '#2f855a', borderRadius: '4px' }}>RAG</span>
                          </div>
                          <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeletePlugin(plugin.id)}>删除</button>
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
                    <label className={listStyles.formLabel}>输出格式类型</label>
                    <select
                      value={formData.output_format?.format_type || 'text'}
                      onChange={(e) => setFormData(prev => ({
                        ...prev,
                        output_format: { ...prev.output_format, format_type: e.target.value as any }
                      }))}
                      className={listStyles.formInput}
                    >
                      <option value="text">纯文本</option>
                      <option value="markdown">Markdown</option>
                      <option value="json">JSON</option>
                      <option value="structured">结构化</option>
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
                    <label className={listStyles.formLabel}>输出示例</label>
                    <textarea
                      value={formData.output_format?.example || ''}
                      onChange={(e) => setFormData(prev => ({
                        ...prev,
                        output_format: { ...prev.output_format, example: e.target.value }
                      }))}
                      className={listStyles.formTextarea}
                      rows={4}
                      placeholder="期望输出的示例..."
                    />
                  </div>
                </div>

                <div className={styles.formSection}>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>最大输出 Token 数</label>
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
                  <h4 style={{ marginTop: 0 }}>路由策略</h4>
                  <p style={{ color: '#888', fontSize: '0.85rem', marginBottom: '12px' }}>
                    此 Agent 如何将任务路由给子 Agent (仅在有子 Agent 时生效)
                  </p>
                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>路由模式</label>
                    <select name="routing_strategy" value={formData.routing_strategy || 'sequential'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="sequential">顺序执行 - 依次执行子 Agent</option>
                      <option value="parallel">并行执行 - 同时执行所有子 Agent</option>
                      <option value="conditional">条件路由 - 根据条件选择执行</option>
                      <option value="handoff">交接模式 - 转交给专家</option>
                      <option value="hierarchical">层级分解 - 分解任务并聚合结果</option>
                      <option value="coordinator">协调者模式 - 父节点整合子节点结果</option>
                      <option value="round_robin">轮询分发 - 均匀分配</option>
                      <option value="load_balanced">负载均衡 - 根据负载分配</option>
                    </select>
                  </div>

                  {/* Strategy-specific tips */}
                  {formData.routing_strategy === 'sequential' && (
                    <div style={{ padding: '12px', background: 'rgba(99, 102, 241, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#6366f1' }}>顺序执行模式</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        子 Agent 依次执行。每个子 Agent 接收前一个 Agent 的累积上下文。
                        适用于: 流水线处理、步骤依赖任务。
                      </p>
                    </div>
                  )}

                  {formData.routing_strategy === 'parallel' && (
                    <div style={{ padding: '12px', background: 'rgba(34, 197, 94, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#22c55e' }}>并行执行模式</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        所有子 Agent 同时执行。完成后收集所有结果。
                        适用于: 独立子任务、批量处理、提高效率。
                      </p>
                    </div>
                  )}

                  {(formData.routing_strategy === 'conditional' || formData.routing_strategy === 'handoff') && (
                    <div style={{ padding: '12px', background: 'rgba(251, 191, 36, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#fbbf24' }}>条件/交接模式</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        根据父 Agent 输出内容路由到特定子 Agent。配置条件匹配关键词。
                        适用于: 意图分类、专家委派。
                      </p>
                      <p style={{ margin: '8px 0 0', fontSize: '0.8rem', color: '#888' }}>
                        提示: 在父 Agent 系统提示中输出与路由条件匹配的关键词。
                      </p>
                    </div>
                  )}

                  {formData.routing_strategy === 'coordinator' && (
                    <div style={{ padding: '12px', background: 'rgba(168, 85, 247, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#a855f7' }}>协调者模式</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        父 Agent 将任务发送给子 Agent，然后接收并综合所有结果。
                        适用于: 多专家协作、共识构建、综合分析。
                      </p>
                    </div>
                  )}

                  {formData.routing_strategy === 'hierarchical' && (
                    <div style={{ padding: '12px', background: 'rgba(236, 72, 153, 0.1)', borderRadius: '8px', marginTop: '12px' }}>
                      <strong style={{ color: '#ec4899' }}>层级分解模式</strong>
                      <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#aaa' }}>
                        父 Agent 分解任务，分发子任务给子 Agent，然后聚合结果。
                        适用于: 复杂任务分解、分治策略。
                      </p>
                    </div>
                  )}
                </div>

                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>执行设置</h4>

                  <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <input
                      type="checkbox"
                      name="streaming_enabled"
                      checked={formData.streaming_enabled !== false}
                      onChange={handleFormChange}
                      id="streaming_enabled"
                    />
                    <label htmlFor="streaming_enabled">启用流式输出</label>
                  </div>

                  <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <input
                      type="checkbox"
                      name="parallel_tool_calls"
                      checked={formData.parallel_tool_calls !== false}
                      onChange={handleFormChange}
                      id="parallel_tool_calls"
                    />
                    <label htmlFor="parallel_tool_calls">允许并行工具调用</label>
                  </div>

                  <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <input
                      type="checkbox"
                      name="content_filter_enabled"
                      checked={formData.content_filter_enabled !== false}
                      onChange={handleFormChange}
                      id="content_filter_enabled"
                    />
                    <label htmlFor="content_filter_enabled">启用内容过滤</label>
                  </div>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>工具选择</label>
                    <select name="tool_choice" value={formData.tool_choice || 'auto'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="auto">自动</option>
                      <option value="none">禁用</option>
                      <option value="required">必须使用</option>
                    </select>
                  </div>
                </div>

                <div className={styles.formSection}>
                  <h4 style={{ marginTop: 0 }}>上下文管理</h4>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>上下文窗口策略</label>
                    <select name="context_window_strategy" value={formData.context_window_strategy || 'sliding'} onChange={handleFormChange} className={listStyles.formInput}>
                      <option value="sliding">滑动窗口</option>
                      <option value="truncate">截断旧消息</option>
                      <option value="summarize">摘要压缩</option>
                      <option value="smart">智能选择</option>
                    </select>
                  </div>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>最大上下文消息数</label>
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
                  <h4 style={{ marginTop: 0 }}>知识库</h4>

                  <div className={listStyles.formGroup}>
                    <label className={listStyles.formLabel}>知识库 ID</label>
                    <input
                      name="knowledge_base"
                      value={formData.knowledge_base || ''}
                      onChange={handleFormChange}
                      className={listStyles.formInput}
                      placeholder="可选的知识库引用"
                    />
                  </div>
                </div>
              </div>
            </form>
          )}
        </div>

        <div className={styles.drawerFooter}>
          <button className={listStyles.buttonLink} onClick={onClose}>取消</button>
          <button className={listStyles.button} onClick={() => setTestModalVisible(true)}>测试</button>
          <button className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSave} disabled={loading}>
            {loading ? '保存中...' : '保存'}
          </button>
        </div>
      </div>

      {/* Test Modal - Chat Interface */}
      <Modal isOpen={testModalVisible} onClose={() => setTestModalVisible(false)} title={`与 ${formData.name || 'Agent'} 对话`}>
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
                <p>开始与 Agent 对话</p>
                <p style={{ fontSize: '0.8rem' }}>在下方输入消息，按 Enter 或点击发送按钮</p>
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
                  <span className={styles.thinkingIndicator}>思考中...</span>
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
              placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
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
                {testLoading ? '...' : '发送'}
              </button>
              <button
                type="button"
                className={listStyles.button}
                onClick={clearChat}
                disabled={testLoading || chatMessages.length === 0}
                style={{ flex: 1, fontSize: '0.8rem' }}
              >
                清空
              </button>
            </div>
          </div>
        </div>

        <div className={listStyles.modalFooter} style={{ marginTop: '12px' }}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setTestModalVisible(false)}>关闭</button>
        </div>
      </Modal>

      {/* Tool Modal */}
      <Modal isOpen={toolModalVisible} onClose={() => setToolModalVisible(false)} title={editingTool ? '编辑工具' : '添加工具'}>
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>工具名称</label>
          <input
            value={toolForm.name || ''}
            onChange={(e) => setToolForm(prev => ({ ...prev, name: e.target.value }))}
            className={listStyles.formInput}
            placeholder="my_tool"
          />
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>描述</label>
          <textarea
            value={toolForm.description || ''}
            onChange={(e) => setToolForm(prev => ({ ...prev, description: e.target.value }))}
            className={listStyles.formTextarea}
            rows={2}
            placeholder="这个工具做什么..."
          />
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>工具类型</label>
          <select
            value={toolForm.tool_type || 'http'}
            onChange={(e) => setToolForm(prev => ({ ...prev, tool_type: e.target.value as any }))}
            className={listStyles.formInput}
          >
            <option value="http">HTTP 请求</option>
            <option value="code">代码执行</option>
            <option value="transform">数据转换</option>
          </select>
        </div>

        {toolForm.tool_type === 'http' && (
          <>
            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>HTTP 方法</label>
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
              <label className={listStyles.formLabel}>请求头 (JSON)</label>
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
              <label className={listStyles.formLabel}>请求体模板 (JSON)</label>
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
              <label className={listStyles.formLabel}>编程语言</label>
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
              <label className={listStyles.formLabel}>代码</label>
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
          <label className={listStyles.formLabel}>超时时间 (秒)</label>
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
          <label htmlFor="approval_required">执行前需要审批</label>
        </div>

        {/* Parameters Section */}
        <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #333' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <label className={listStyles.formLabel} style={{ margin: 0 }}>参数</label>
            <button type="button" className={listStyles.buttonLink} onClick={handleAddParameter}>+ 添加参数</button>
          </div>

          {(toolForm.parameters || []).map((param, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', padding: '8px', background: '#1a1a2e', borderRadius: '4px' }}>
              <span style={{ flex: 1 }}>{param.name} ({param.type}){param.required && ' *'}</span>
              <button type="button" className={listStyles.buttonLink} style={{ color: '#f56565' }} onClick={() => handleDeleteParameter(param.name)}>移除</button>
            </div>
          ))}
        </div>

        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setToolModalVisible(false)}>取消</button>
          <button type="button" className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSaveTool}>
            {editingTool ? '更新工具' : '添加工具'}
          </button>
        </div>
      </Modal>

      {/* Parameter Modal */}
      <Modal isOpen={paramModalVisible} onClose={() => setParamModalVisible(false)} title="添加参数">
        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>参数名称</label>
          <input
            value={paramForm.name || ''}
            onChange={(e) => setParamForm(prev => ({ ...prev, name: e.target.value }))}
            className={listStyles.formInput}
            placeholder="param_name"
          />
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>类型</label>
          <select
            value={paramForm.type || 'string'}
            onChange={(e) => setParamForm(prev => ({ ...prev, type: e.target.value as any }))}
            className={listStyles.formInput}
          >
            <option value="string">字符串</option>
            <option value="integer">整数</option>
            <option value="number">数字</option>
            <option value="boolean">布尔值</option>
            <option value="array">数组</option>
            <option value="object">对象</option>
          </select>
        </div>

        <div className={listStyles.formGroup}>
          <label className={listStyles.formLabel}>描述</label>
          <input
            value={paramForm.description || ''}
            onChange={(e) => setParamForm(prev => ({ ...prev, description: e.target.value }))}
            className={listStyles.formInput}
            placeholder="参数描述"
          />
        </div>

        <div className={listStyles.formGroup} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <input
            type="checkbox"
            checked={paramForm.required || false}
            onChange={(e) => setParamForm(prev => ({ ...prev, required: e.target.checked }))}
            id="param_required"
          />
          <label htmlFor="param_required">必填</label>
        </div>

        <div className={listStyles.modalFooter}>
          <button type="button" className={listStyles.buttonLink} onClick={() => setParamModalVisible(false)}>取消</button>
          <button type="button" className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSaveParameter}>添加</button>
        </div>
      </Modal>

      {/* Plugin Modal */}
      <Modal isOpen={pluginModalVisible} onClose={() => setPluginModalVisible(false)} title={`添加 ${pluginType.toUpperCase()}`}>
        {pluginType === 'mcp' && (
          <>
            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>名称</label>
              <input
                value={pluginForm.name || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, name: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my-mcp-server"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>命令</label>
              <input
                value={pluginForm.command || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, command: e.target.value }))}
                className={listStyles.formInput}
                placeholder="npx -y @modelcontextprotocol/server-xxx"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>参数 (空格分隔)</label>
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
              <label className={listStyles.formLabel}>名称</label>
              <input
                value={pluginForm.name || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, name: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my_skill"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>描述</label>
              <textarea
                value={pluginForm.description || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, description: e.target.value }))}
                className={listStyles.formTextarea}
                rows={2}
                placeholder="这个技能做什么..."
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>模块路径</label>
              <input
                value={pluginForm.module_path || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, module_path: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my_module.skills"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>函数名称</label>
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
              <label className={listStyles.formLabel}>名称</label>
              <input
                value={pluginForm.name || ''}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, name: e.target.value }))}
                className={listStyles.formInput}
                placeholder="my_knowledge_base"
              />
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>RAG 类型</label>
              <select
                value={pluginForm.rag_type || 'vector_db'}
                onChange={(e) => setPluginForm((prev: any) => ({ ...prev, rag_type: e.target.value }))}
                className={listStyles.formInput}
              >
                <option value="vector_db">向量数据库</option>
                <option value="elasticsearch">Elasticsearch</option>
                <option value="pinecone">Pinecone</option>
                <option value="chroma">Chroma</option>
                <option value="qdrant">Qdrant</option>
              </select>
            </div>

            <div className={listStyles.formGroup}>
              <label className={listStyles.formLabel}>连接字符串</label>
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
          <button type="button" className={listStyles.buttonLink} onClick={() => setPluginModalVisible(false)}>取消</button>
          <button type="button" className={`${listStyles.button} ${listStyles.buttonPrimary}`} onClick={handleSavePlugin}>
            注册
          </button>
        </div>
      </Modal>
    </>
  );
};

export default AgentEditor;
