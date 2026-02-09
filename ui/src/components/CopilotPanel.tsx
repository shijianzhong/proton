import React, { useState, useEffect, useRef } from 'react';
import { api, CopilotEvent, CopilotMessage, CopilotConfig } from '../api/client';
import styles from './CopilotPanel.module.css';

interface CopilotPanelProps {
  visible: boolean;
  workflowId?: string | null;  // If provided, load/save workflow-level config
  onClose: () => void;
  onWorkflowGenerated?: (workflowId: string) => void;
}

const CopilotPanel: React.FC<CopilotPanelProps> = ({
  visible,
  workflowId,
  onClose,
  onWorkflowGenerated,
}) => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentWorkflowId, setCurrentWorkflowId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);

  // Config state
  const [config, setConfig] = useState<CopilotConfig | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [configApiKey, setConfigApiKey] = useState('');
  const [configProvider, setConfigProvider] = useState('openai');
  const [configModel, setConfigModel] = useState('gpt-4');
  const [configBaseUrl, setConfigBaseUrl] = useState('');
  const [isSavingConfig, setIsSavingConfig] = useState(false);
  const [isWorkflowLevel, setIsWorkflowLevel] = useState(false);

  // Load config on mount - workflow-level if workflowId provided, otherwise global
  useEffect(() => {
    if (visible) {
      const loadConfig = workflowId
        ? api.getWorkflowCopilotConfig(workflowId)
        : api.getCopilotConfig();

      loadConfig
        .then(cfg => {
          setConfig(cfg);
          setConfigProvider(cfg.provider);
          setConfigModel(cfg.model);
          setConfigBaseUrl(cfg.base_url || '');
          setIsWorkflowLevel(!!workflowId && cfg.is_workflow_level);
          // Only show config panel if global config is not set (when no workflowId)
          // For workflow-level, user can manually open config to override
          if (!workflowId && !cfg.api_key_configured) {
            setShowConfig(true);
          }
        })
        .catch(err => console.error('Failed to load config:', err));
    }
  }, [visible, workflowId]);

  // Create session when config is ready
  useEffect(() => {
    if (visible && !sessionId && config && config.api_key_configured) {
      // Create session with workflow context if editing existing workflow
      api.createCopilotSession(workflowId)
        .then(res => setSessionId(res.session_id))
        .catch(err => setError(`创建会话失败: ${err.message}`));
    }
  }, [visible, sessionId, config, workflowId]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current();
      }
    };
  }, []);

  const handleSaveConfig = async () => {
    setIsSavingConfig(true);
    try {
      const configData = {
        provider: configProvider,
        model: configModel,
        api_key: configApiKey || undefined,
        base_url: configBaseUrl || undefined,
      };

      const result = workflowId
        ? await api.updateWorkflowCopilotConfig(workflowId, configData)
        : await api.updateCopilotConfig(configData);

      setConfig(result.config);
      setIsWorkflowLevel(!!workflowId && result.config.is_workflow_level);
      setShowConfig(false);
      setConfigApiKey(''); // Clear for security

      // Create session if now configured
      if (result.config.api_key_configured && !sessionId) {
        const session = await api.createCopilotSession(workflowId);
        setSessionId(session.session_id);
      }
    } catch (err: any) {
      setError(`保存配置失败: ${err.message}`);
    } finally {
      setIsSavingConfig(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || !sessionId || isGenerating) return;

    const userMessage = input.trim();
    setInput('');
    setError(null);
    setMessages(prev => [...prev, { role: 'user', content: userMessage, timestamp: new Date().toISOString() }]);
    setIsGenerating(true);

    let assistantContent = '';

    abortRef.current = api.copilotChat(
      sessionId,
      userMessage,
      // onEvent
      (event: CopilotEvent) => {
        if (event.type === 'content' && event.delta) {
          assistantContent += event.delta;
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant') {
              return [...prev.slice(0, -1), { ...last, content: assistantContent }];
            }
            return [...prev, { role: 'assistant', content: assistantContent, timestamp: new Date().toISOString() }];
          });
        } else if (event.type === 'tool_start') {
          // Show tool execution indicator
          const toolMsg = `\n\n🔧 正在执行: ${event.tool_name}...`;
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant') {
              return [...prev.slice(0, -1), { ...last, content: assistantContent + toolMsg }];
            }
            return prev;
          });
        } else if (event.type === 'workflow_created' && event.workflow_id) {
          setCurrentWorkflowId(event.workflow_id);
          onWorkflowGenerated?.(event.workflow_id);
        } else if (event.type === 'workflow_updated' && event.workflow_id) {
          setCurrentWorkflowId(event.workflow_id);
        } else if (event.type === 'error' && event.error) {
          setError(event.error);
        }
      },
      // onComplete
      () => {
        setIsGenerating(false);
        abortRef.current = null;
      },
      // onError
      (err) => {
        setError(err.message);
        setIsGenerating(false);
        abortRef.current = null;
      }
    );
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleNewSession = async () => {
    if (abortRef.current) {
      abortRef.current();
    }
    setMessages([]);
    setCurrentWorkflowId(null);
    setError(null);
    setSessionId(null);

    try {
      const res = await api.createCopilotSession(workflowId);
      setSessionId(res.session_id);
    } catch (err: any) {
      setError(`创建会话失败: ${err.message}`);
    }
  };

  if (!visible) return null;

  // Config panel
  if (showConfig) {
    return (
      <div className={styles.panel}>
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            <span className={styles.icon}>⚙️</span>
            <h3>Copilot 设置</h3>
          </div>
          <div className={styles.headerActions}>
            <button
              className={styles.closeBtn}
              onClick={() => {
                if (config?.api_key_configured) {
                  setShowConfig(false);
                } else {
                  // If no API key configured, go back to chat but show notice
                  setShowConfig(false);
                  setError('请先配置 API Key 才能使用 Copilot');
                }
              }}
              title={config?.api_key_configured ? '关闭设置' : '返回（需要配置 API Key）'}
            >
              ×
            </button>
          </div>
        </div>

        <div className={styles.configPanel}>
          <p className={styles.configIntro}>
            {workflowId ? (
              <>
                <strong>工作流级别配置</strong> - 此配置仅对当前工作流生效，优先级高于全局设置。
                如果留空，将使用全局默认配置。
              </>
            ) : (
              <>
                配置 Workflow Copilot 使用的 LLM 服务商。支持 OpenAI、智谱、DeepSeek、通义千问、
                Moonshot、Anthropic，以及 OpenAI 兼容 API（如 Ollama）。
              </>
            )}
          </p>

          <div className={styles.formGroup}>
            <label>服务商</label>
            <select
              value={configProvider}
              onChange={(e) => {
                setConfigProvider(e.target.value);
                // Reset model when provider changes
                const providerModels: Record<string, string> = {
                  'openai': 'gpt-4',
                  'azure': 'gpt-4',
                  'anthropic': 'claude-3-opus-20240229',
                  'zhipu': 'glm-4',
                  'deepseek': 'deepseek-chat',
                  'qwen': 'qwen-plus',
                  'ollama': 'llama2',
                  'moonshot': 'moonshot-v1-8k',
                  'yi': 'yi-large',
                  'baichuan': 'Baichuan2-Turbo',
                };
                setConfigModel(providerModels[e.target.value] || 'gpt-4');
              }}
            >
              <option value="openai">OpenAI</option>
              <option value="azure">Azure OpenAI</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="zhipu">智谱 AI (GLM)</option>
              <option value="deepseek">DeepSeek</option>
              <option value="qwen">通义千问 (Qwen)</option>
              <option value="moonshot">Moonshot</option>
              <option value="yi">零一万物 (Yi)</option>
              <option value="baichuan">百川 (Baichuan)</option>
              <option value="ollama">Ollama (本地部署)</option>
            </select>
          </div>

          <div className={styles.formGroup}>
            <label>API Key {configProvider !== 'ollama' && '*'}</label>
            <input
              type="password"
              value={configApiKey}
              onChange={(e) => setConfigApiKey(e.target.value)}
              placeholder={config?.api_key_configured ? '••••••••' : '请输入 API Key'}
            />
            <span className={styles.hint}>
              {config?.api_key_configured
                ? `当前: ${config.api_key_preview}`
                : configProvider === 'ollama'
                  ? 'Ollama 无需 API Key'
                  : '必填，或通过环境变量设置'}
            </span>
          </div>

          <div className={styles.formGroup}>
            <label>模型</label>
            <select value={configModel} onChange={(e) => setConfigModel(e.target.value)}>
              {configProvider === 'openai' && (
                <>
                  <option value="gpt-4">GPT-4</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4o-mini">GPT-4o Mini</option>
                  <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                </>
              )}
              {configProvider === 'azure' && (
                <>
                  <option value="gpt-4">GPT-4</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                  <option value="gpt-35-turbo">GPT-3.5 Turbo</option>
                </>
              )}
              {configProvider === 'anthropic' && (
                <>
                  <option value="claude-3-opus-20240229">Claude 3 Opus</option>
                  <option value="claude-3-sonnet-20240229">Claude 3 Sonnet</option>
                  <option value="claude-3-haiku-20240307">Claude 3 Haiku</option>
                </>
              )}
              {configProvider === 'zhipu' && (
                <>
                  <option value="glm-4">GLM-4</option>
                  <option value="glm-4-plus">GLM-4 Plus</option>
                  <option value="glm-4-air">GLM-4 Air</option>
                  <option value="glm-4-airx">GLM-4 AirX</option>
                  <option value="glm-4-flash">GLM-4 Flash</option>
                  <option value="glm-4v">GLM-4V (视觉)</option>
                </>
              )}
              {configProvider === 'deepseek' && (
                <>
                  <option value="deepseek-chat">DeepSeek Chat</option>
                  <option value="deepseek-coder">DeepSeek Coder</option>
                </>
              )}
              {configProvider === 'qwen' && (
                <>
                  <option value="qwen-turbo">Qwen Turbo</option>
                  <option value="qwen-plus">Qwen Plus</option>
                  <option value="qwen-max">Qwen Max</option>
                  <option value="qwen-max-longcontext">Qwen Max (长上下文)</option>
                </>
              )}
              {configProvider === 'moonshot' && (
                <>
                  <option value="moonshot-v1-8k">Moonshot V1 8K</option>
                  <option value="moonshot-v1-32k">Moonshot V1 32K</option>
                  <option value="moonshot-v1-128k">Moonshot V1 128K</option>
                </>
              )}
              {configProvider === 'yi' && (
                <>
                  <option value="yi-large">Yi Large</option>
                  <option value="yi-medium">Yi Medium</option>
                  <option value="yi-spark">Yi Spark</option>
                </>
              )}
              {configProvider === 'baichuan' && (
                <>
                  <option value="Baichuan2-Turbo">Baichuan2 Turbo</option>
                  <option value="Baichuan2-Turbo-192k">Baichuan2 Turbo 192K</option>
                </>
              )}
              {configProvider === 'ollama' && (
                <>
                  <option value="llama2">Llama 2</option>
                  <option value="llama3">Llama 3</option>
                  <option value="mistral">Mistral</option>
                  <option value="codellama">Code Llama</option>
                  <option value="qwen">Qwen</option>
                </>
              )}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label>API 地址 (可选)</label>
            <input
              type="text"
              value={configBaseUrl}
              onChange={(e) => setConfigBaseUrl(e.target.value)}
              placeholder={configProvider === 'ollama' ? 'http://localhost:11434/v1' : '留空使用默认地址'}
            />
            <span className={styles.hint}>
              用于自定义部署或代理地址
            </span>
          </div>

          <button
            className={styles.saveConfigBtn}
            onClick={handleSaveConfig}
            disabled={isSavingConfig || (configProvider !== 'ollama' && !configApiKey && !config?.api_key_configured)}
          >
            {isSavingConfig ? '保存中...' : '保存并继续'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <span className={styles.icon}>🤖</span>
          <h3>Workflow Copilot</h3>
        </div>
        <div className={styles.headerActions}>
          <button
            className={styles.configBtn}
            onClick={() => setShowConfig(true)}
            title="设置"
          >
            ⚙️
          </button>
          <button
            className={styles.newBtn}
            onClick={handleNewSession}
            title="新会话"
          >
            +
          </button>
          <button
            className={styles.closeBtn}
            onClick={onClose}
          >
            ×
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className={styles.errorBanner}>
          {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Chat Messages */}
      <div className={styles.chatArea}>
        {messages.length === 0 && (
          <div className={styles.welcomeMessage}>
            <h4>欢迎使用 Workflow Copilot！</h4>
            <p>
              {workflowId
                ? '我可以帮你修改和优化当前工作流，或者创建新的工作流。'
                : '描述你想要创建的工作流，我会帮你设计和生成。'}
            </p>
            <div className={styles.suggestions}>
              <p>你可以这样说：</p>
              <ul>
                {workflowId ? (
                  <>
                    <li>"在当前工作流中添加一个邮件通知节点"</li>
                    <li>"优化当前工作流的路由策略"</li>
                    <li>"为这个工作流添加错误处理逻辑"</li>
                  </>
                ) : (
                  <>
                    <li>"创建一个客服工作流，包含问题分诊和专家处理"</li>
                    <li>"构建一个内容审核流水线，包含撰写、编辑和审核"</li>
                    <li>"设计一个数据分析工作流，支持并行处理报表"</li>
                  </>
                )}
              </ul>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`${styles.message} ${styles[msg.role]}`}
          >
            <div className={styles.messageRole}>
              {msg.role === 'user' ? '👤 你' : '🤖 Copilot'}
            </div>
            <div className={styles.messageContent}>
              {msg.content}
            </div>
          </div>
        ))}

        {isGenerating && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className={`${styles.message} ${styles.assistant}`}>
            <div className={styles.messageRole}>🤖 Copilot</div>
            <div className={styles.thinking}>
              <span className={styles.dot}></span>
              <span className={styles.dot}></span>
              <span className={styles.dot}></span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Generated Workflow Preview */}
      {currentWorkflowId && (
        <div className={styles.workflowPreview}>
          <span>✅ 工作流: {currentWorkflowId.slice(0, 8)}...</span>
          <button
            onClick={() => onWorkflowGenerated?.(currentWorkflowId)}
            className={styles.openBtn}
          >
            在编辑器中打开
          </button>
        </div>
      )}

      {/* Input Area */}
      <div className={styles.inputArea}>
        {!sessionId && (
          <div style={{
            padding: '8px 12px',
            backgroundColor: '#fff3cd',
            border: '1px solid #ffc107',
            borderRadius: '4px',
            marginBottom: '8px',
            fontSize: '13px',
            color: '#856404'
          }}>
            ⚠️ 请先在设置中配置 API Key 才能使用 Copilot
            <button
              onClick={() => setShowConfig(true)}
              style={{
                marginLeft: '8px',
                padding: '2px 8px',
                fontSize: '12px',
                cursor: 'pointer',
                backgroundColor: '#ffc107',
                border: 'none',
                borderRadius: '3px',
                color: '#000'
              }}
            >
              前往配置
            </button>
          </div>
        )}
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder={
            !sessionId
              ? "请先配置 API Key..."
              : workflowId
                ? "描述你想对当前工作流做的修改，或创建新的工作流..."
                : "描述你想要创建的工作流..."
          }
          disabled={isGenerating || !sessionId}
          rows={3}
        />
        <button
          onClick={handleSend}
          disabled={isGenerating || !input.trim() || !sessionId}
          className={styles.sendBtn}
        >
          {isGenerating ? '...' : '发送'}
        </button>
      </div>
    </div>
  );
};

export default CopilotPanel;
