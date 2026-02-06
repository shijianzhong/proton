import React, { useState, useEffect } from 'react';
import { api, SearchConfig, CopilotConfig, EmailConfig } from '../api/client';
import styles from './SettingsPanel.module.css';

interface SettingsPanelProps {
  visible: boolean;
  onClose: () => void;
  isPage?: boolean;  // When true, renders as a full page instead of overlay
}

type TabType = 'search' | 'copilot' | 'email';

const SettingsPanel: React.FC<SettingsPanelProps> = ({ visible, onClose, isPage = false }) => {
  const [activeTab, setActiveTab] = useState<TabType>('search');

  // Search config state
  const [searchConfig, setSearchConfig] = useState<SearchConfig | null>(null);
  const [searchProvider, setSearchProvider] = useState('bing');
  const [searxngBaseUrl, setSearxngBaseUrl] = useState('');
  const [serperApiKey, setSerperApiKey] = useState('');
  const [braveApiKey, setBraveApiKey] = useState('');
  const [bingApiKey, setBingApiKey] = useState('');
  const [googleApiKey, setGoogleApiKey] = useState('');
  const [googleCx, setGoogleCx] = useState('');
  const [isSavingSearch, setIsSavingSearch] = useState(false);
  const [searchTestResult, setSearchTestResult] = useState<string | null>(null);
  const [isTestingSearch, setIsTestingSearch] = useState(false);

  // Copilot config state
  const [copilotConfig, setCopilotConfig] = useState<CopilotConfig | null>(null);
  const [copilotProvider, setCopilotProvider] = useState('openai');
  const [copilotModel, setCopilotModel] = useState('gpt-4');
  const [copilotApiKey, setCopilotApiKey] = useState('');
  const [copilotBaseUrl, setCopilotBaseUrl] = useState('');
  const [isSavingCopilot, setIsSavingCopilot] = useState(false);

  // Email config state
  const [emailConfig, setEmailConfig] = useState<EmailConfig | null>(null);
  const [emailMethod, setEmailMethod] = useState('auto');
  const [resendApiKey, setResendApiKey] = useState('');
  const [resendFrom, setResendFrom] = useState('');
  const [smtpHost, setSmtpHost] = useState('smtp.gmail.com');
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUser, setSmtpUser] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [smtpFrom, setSmtpFrom] = useState('');
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [isSavingEmail, setIsSavingEmail] = useState(false);
  const [testEmailAddress, setTestEmailAddress] = useState('');
  const [emailTestResult, setEmailTestResult] = useState<string | null>(null);
  const [isTestingEmail, setIsTestingEmail] = useState(false);

  const [error, setError] = useState<string | null>(null);

  // Load configs on mount
  useEffect(() => {
    if (visible) {
      loadSearchConfig();
      loadCopilotConfig();
      loadEmailConfig();
    }
  }, [visible]);

  const loadSearchConfig = async () => {
    try {
      const config = await api.getSearchConfig();
      setSearchConfig(config);
      setSearchProvider(config.provider);
      setSearxngBaseUrl(config.searxng_base_url || '');
    } catch (err: any) {
      console.error('Failed to load search config:', err);
    }
  };

  const loadCopilotConfig = async () => {
    try {
      const config = await api.getCopilotConfig();
      setCopilotConfig(config);
      setCopilotProvider(config.provider);
      setCopilotModel(config.model);
      setCopilotBaseUrl(config.base_url || '');
    } catch (err: any) {
      console.error('Failed to load copilot config:', err);
    }
  };

  const loadEmailConfig = async () => {
    try {
      const config = await api.getEmailConfig();
      setEmailConfig(config);
      setEmailMethod(config.preferred_method);
      setResendFrom(config.resend.from || '');
      setSmtpHost(config.smtp.host || 'smtp.gmail.com');
      setSmtpPort(config.smtp.port || 587);
      setSmtpUser(config.smtp.user || '');
      setSmtpFrom(config.smtp.from || '');
      setSmtpUseTls(config.smtp.use_tls);
    } catch (err: any) {
      console.error('Failed to load email config:', err);
    }
  };

  const handleSaveSearch = async () => {
    setIsSavingSearch(true);
    setError(null);
    try {
      const result = await api.updateSearchConfig({
        provider: searchProvider,
        searxng_base_url: searxngBaseUrl || undefined,
        serper_api_key: serperApiKey || undefined,
        brave_api_key: braveApiKey || undefined,
        bing_api_key: bingApiKey || undefined,
        google_api_key: googleApiKey || undefined,
        google_cx: googleCx || undefined,
      });
      setSearchConfig(result.config);
      // Clear sensitive fields
      setSerperApiKey('');
      setBraveApiKey('');
      setBingApiKey('');
      setGoogleApiKey('');
      setGoogleCx('');
    } catch (err: any) {
      setError(`保存搜索配置失败: ${err.message}`);
    } finally {
      setIsSavingSearch(false);
    }
  };

  const handleTestSearch = async () => {
    setIsTestingSearch(true);
    setSearchTestResult(null);
    try {
      const result = await api.testSearch('AI最新资讯', searchProvider);
      setSearchTestResult(result.result);
    } catch (err: any) {
      setSearchTestResult(`错误: ${err.message}`);
    } finally {
      setIsTestingSearch(false);
    }
  };

  const handleSaveCopilot = async () => {
    setIsSavingCopilot(true);
    setError(null);
    try {
      const result = await api.updateCopilotConfig({
        provider: copilotProvider,
        model: copilotModel,
        api_key: copilotApiKey || undefined,
        base_url: copilotBaseUrl || undefined,
      });
      setCopilotConfig(result.config);
      setCopilotApiKey(''); // Clear for security
    } catch (err: any) {
      setError(`保存 Copilot 配置失败: ${err.message}`);
    } finally {
      setIsSavingCopilot(false);
    }
  };

  const handleSaveEmail = async () => {
    setIsSavingEmail(true);
    setError(null);
    try {
      const result = await api.updateEmailConfig({
        preferred_method: emailMethod,
        resend_api_key: resendApiKey || undefined,
        resend_from: resendFrom || undefined,
        smtp_host: smtpHost || undefined,
        smtp_port: smtpPort || undefined,
        smtp_user: smtpUser || undefined,
        smtp_password: smtpPassword || undefined,
        smtp_from: smtpFrom || undefined,
        smtp_use_tls: smtpUseTls,
      });
      setEmailConfig(result.config);
      // Clear sensitive fields
      setResendApiKey('');
      setSmtpPassword('');
    } catch (err: any) {
      setError(`保存邮件配置失败: ${err.message}`);
    } finally {
      setIsSavingEmail(false);
    }
  };

  const handleTestEmail = async () => {
    if (!testEmailAddress) {
      setEmailTestResult('错误: 请输入邮箱地址');
      return;
    }
    setIsTestingEmail(true);
    setEmailTestResult(null);
    try {
      const result = await api.testEmail(testEmailAddress);
      setEmailTestResult(result.message);
    } catch (err: any) {
      setEmailTestResult(`错误: ${err.message}`);
    } finally {
      setIsTestingEmail(false);
    }
  };

  if (!visible) return null;

  // Page mode - render without overlay
  if (isPage) {
    return (
      <div className={styles.pageContainer}>
        <div className={styles.pageHeader}>
          <h2>系统设置</h2>
          <p className={styles.pageSubtitle}>配置全局系统设置，这些设置将应用于所有工作流（除非工作流有单独配置）</p>
        </div>

        {error && (
          <div className={styles.errorBanner}>
            {error}
            <button onClick={() => setError(null)}>×</button>
          </div>
        )}

        <div className={styles.pageTabs}>
          <button
            className={`${styles.pageTab} ${activeTab === 'search' ? styles.active : ''}`}
            onClick={() => setActiveTab('search')}
          >
            🔍 搜索引擎
          </button>
          <button
            className={`${styles.pageTab} ${activeTab === 'email' ? styles.active : ''}`}
            onClick={() => setActiveTab('email')}
          >
            📧 邮件服务
          </button>
          <button
            className={`${styles.pageTab} ${activeTab === 'copilot' ? styles.active : ''}`}
            onClick={() => setActiveTab('copilot')}
          >
            🤖 AI Copilot
          </button>
        </div>

        <div className={styles.pageContent}>
          {renderTabContent()}
        </div>
      </div>
    );
  }

  // Extract tab content to a shared function
  function renderTabContent() {
    if (activeTab === 'search') {
      return (
        <div className={styles.section}>
          <p className={styles.intro}>
            配置网页搜索引擎。推荐国内用户使用 Bing（无需翻墙）。
          </p>

          <div className={styles.formGroup}>
            <label>搜索引擎</label>
            <select value={searchProvider} onChange={(e) => setSearchProvider(e.target.value)}>
              {searchConfig?.available_providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} {p.china_accessible ? '✓国内可用' : ''} {p.configured ? '(已配置)' : ''}
                </option>
              ))}
            </select>
            <span className={styles.hint}>
              {searchConfig?.available_providers.find(p => p.id === searchProvider)?.description}
            </span>
          </div>

          {searchProvider === 'searxng' && (
            <div className={styles.formGroup}>
              <label>SearXNG 服务地址 *</label>
              <input
                type="text"
                value={searxngBaseUrl}
                onChange={(e) => setSearxngBaseUrl(e.target.value)}
                placeholder="http://localhost:8080"
              />
              <span className={styles.hint}>
                {searchConfig?.searxng_configured
                  ? `当前: ${searchConfig.searxng_base_url}`
                  : '部署命令: docker run -p 8080:8080 searxng/searxng'}
              </span>
            </div>
          )}

          {searchProvider === 'serper' && (
            <div className={styles.formGroup}>
              <label>Serper API Key *</label>
              <input
                type="password"
                value={serperApiKey}
                onChange={(e) => setSerperApiKey(e.target.value)}
                placeholder={searchConfig?.serper_configured ? '••••••••' : '请输入 API Key'}
              />
              <span className={styles.hint}>
                {searchConfig?.serper_configured
                  ? `当前: ${searchConfig.serper_api_key_preview}`
                  : '在 serper.dev 获取 (每月 2,500 次免费)'}
              </span>
            </div>
          )}

          {searchProvider === 'brave' && (
            <div className={styles.formGroup}>
              <label>Brave API Key *</label>
              <input
                type="password"
                value={braveApiKey}
                onChange={(e) => setBraveApiKey(e.target.value)}
                placeholder={searchConfig?.brave_configured ? '••••••••' : '请输入 API Key'}
              />
              <span className={styles.hint}>
                {searchConfig?.brave_configured
                  ? `当前: ${searchConfig.brave_api_key_preview}`
                  : '在 brave.com/search/api 获取 (每月 2,000 次免费)'}
              </span>
            </div>
          )}

          {searchProvider === 'bing' && (
            <div className={styles.formGroup}>
              <label>Bing API Key (可选)</label>
              <input
                type="password"
                value={bingApiKey}
                onChange={(e) => setBingApiKey(e.target.value)}
                placeholder={searchConfig?.bing_configured ? '••••••••' : '可选 - 不填也能用'}
              />
              <span className={styles.hint}>
                {searchConfig?.bing_configured
                  ? `当前: ${searchConfig.bing_api_key_preview}`
                  : 'Bing 无需 API Key 即可使用（网页抓取），有 Key 效果更好'}
              </span>
            </div>
          )}

          {searchProvider === 'google' && (
            <>
              <div className={styles.formGroup}>
                <label>Google API Key *</label>
                <input
                  type="password"
                  value={googleApiKey}
                  onChange={(e) => setGoogleApiKey(e.target.value)}
                  placeholder={searchConfig?.google_configured ? '••••••••' : '请输入 API Key'}
                />
              </div>
              <div className={styles.formGroup}>
                <label>Google CX (搜索引擎 ID) *</label>
                <input
                  type="text"
                  value={googleCx}
                  onChange={(e) => setGoogleCx(e.target.value)}
                  placeholder="请输入搜索引擎 ID"
                />
                <span className={styles.hint}>
                  在 programmablesearchengine.google.com 创建
                </span>
              </div>
            </>
          )}

          <div className={styles.buttonGroup}>
            <button
              className={styles.saveBtn}
              onClick={handleSaveSearch}
              disabled={isSavingSearch}
            >
              {isSavingSearch ? '保存中...' : '保存'}
            </button>
            <button
              className={styles.testBtn}
              onClick={handleTestSearch}
              disabled={isTestingSearch}
            >
              {isTestingSearch ? '测试中...' : '测试搜索'}
            </button>
          </div>

          {searchTestResult && (
            <div className={styles.testResult}>
              <h4>测试结果:</h4>
              <pre>{searchTestResult}</pre>
            </div>
          )}
        </div>
      );
    }

    if (activeTab === 'email') {
      return (
        <div className={styles.section}>
          <p className={styles.intro}>
            配置邮件发送服务。推荐使用 Resend API（适合 Cloudflare 等自定义域名）。
          </p>

          <div className={styles.formGroup}>
            <label>发送方式</label>
            <select value={emailMethod} onChange={(e) => setEmailMethod(e.target.value)}>
              <option value="auto">自动 (优先 Resend)</option>
              <option value="resend">Resend API</option>
              <option value="smtp">SMTP</option>
            </select>
            <span className={styles.hint}>
              {emailConfig?.active_method === 'resend' && '当前使用: Resend API'}
              {emailConfig?.active_method === 'smtp' && '当前使用: SMTP'}
              {emailConfig?.active_method === 'none' && '未配置'}
            </span>
          </div>

          {/* Resend Configuration */}
          <div style={{ marginTop: '16px', padding: '12px', background: '#313244', borderRadius: '8px' }}>
            <h4 style={{ margin: '0 0 12px 0', color: '#89b4fa' }}>Resend API (推荐)</h4>
            <p style={{ fontSize: '12px', color: '#a6adc8', marginBottom: '12px' }}>
              适合 Cloudflare 等自定义域名，在 resend.com 获取 API Key
            </p>

            <div className={styles.formGroup}>
              <label>Resend API Key</label>
              <input
                type="password"
                value={resendApiKey}
                onChange={(e) => setResendApiKey(e.target.value)}
                placeholder={emailConfig?.resend.configured ? '••••••••' : '请输入 API Key (re_xxxxx)'}
              />
              {emailConfig?.resend.configured && (
                <span className={styles.hint}>当前: {emailConfig.resend.api_key_preview}</span>
              )}
            </div>

            <div className={styles.formGroup}>
              <label>发件人地址</label>
              <input
                type="text"
                value={resendFrom}
                onChange={(e) => setResendFrom(e.target.value)}
                placeholder="noreply@yourdomain.com"
              />
              <span className={styles.hint}>
                必须是在 Resend 中已验证的域名
              </span>
            </div>
          </div>

          {/* SMTP Configuration */}
          <div style={{ marginTop: '16px', padding: '12px', background: '#313244', borderRadius: '8px' }}>
            <h4 style={{ margin: '0 0 12px 0', color: '#a6e3a1' }}>SMTP (传统方式)</h4>
            <p style={{ fontSize: '12px', color: '#a6adc8', marginBottom: '12px' }}>
              适用于 Gmail、QQ邮箱、163邮箱、Outlook 等
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div className={styles.formGroup}>
                <label>SMTP 服务器</label>
                <input
                  type="text"
                  value={smtpHost}
                  onChange={(e) => setSmtpHost(e.target.value)}
                  placeholder="smtp.gmail.com"
                />
              </div>

              <div className={styles.formGroup}>
                <label>端口</label>
                <input
                  type="number"
                  value={smtpPort}
                  onChange={(e) => setSmtpPort(parseInt(e.target.value) || 587)}
                  placeholder="587"
                />
              </div>
            </div>

            <div className={styles.formGroup}>
              <label>用户名 (邮箱地址)</label>
              <input
                type="text"
                value={smtpUser}
                onChange={(e) => setSmtpUser(e.target.value)}
                placeholder="your_email@gmail.com"
              />
            </div>

            <div className={styles.formGroup}>
              <label>密码 / 授权码</label>
              <input
                type="password"
                value={smtpPassword}
                onChange={(e) => setSmtpPassword(e.target.value)}
                placeholder={emailConfig?.smtp.configured ? '••••••••' : '请输入密码或授权码'}
              />
              <span className={styles.hint}>
                Gmail 请使用应用专用密码，QQ/163 请使用授权码
              </span>
            </div>

            <div className={styles.formGroup}>
              <label>发件人地址 (可选)</label>
              <input
                type="text"
                value={smtpFrom}
                onChange={(e) => setSmtpFrom(e.target.value)}
                placeholder="留空则使用用户名"
              />
            </div>

            <div className={styles.formGroup}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={smtpUseTls}
                  onChange={(e) => setSmtpUseTls(e.target.checked)}
                  style={{ width: 'auto' }}
                />
                使用 TLS (推荐用于端口 587)
              </label>
              <span className={styles.hint}>
                163邮箱使用端口 465 时请取消勾选
              </span>
            </div>
          </div>

          <div className={styles.buttonGroup}>
            <button
              className={styles.saveBtn}
              onClick={handleSaveEmail}
              disabled={isSavingEmail}
            >
              {isSavingEmail ? '保存中...' : '保存'}
            </button>
          </div>

          {/* Test Email */}
          <div style={{ marginTop: '16px', padding: '12px', background: '#313244', borderRadius: '8px' }}>
            <h4 style={{ margin: '0 0 12px 0', color: '#f9e2af' }}>发送测试邮件</h4>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="email"
                value={testEmailAddress}
                onChange={(e) => setTestEmailAddress(e.target.value)}
                placeholder="your_email@example.com"
                style={{
                  flex: 1,
                  padding: '10px 12px',
                  background: '#45475a',
                  border: '1px solid #585b70',
                  borderRadius: '6px',
                  color: '#cdd6f4',
                }}
              />
              <button
                className={styles.testBtn}
                onClick={handleTestEmail}
                disabled={isTestingEmail || !testEmailAddress}
              >
                {isTestingEmail ? '发送中...' : '发送测试'}
              </button>
            </div>
          </div>

          {emailTestResult && (
            <div className={styles.testResult}>
              <h4>测试结果:</h4>
              <pre>{emailTestResult}</pre>
            </div>
          )}
        </div>
      );
    }

    if (activeTab === 'copilot') {
      return (
        <div className={styles.section}>
          <p className={styles.intro}>
            配置 Workflow Copilot 使用的 LLM 服务商。此为全局默认配置，各工作流可单独覆盖。
          </p>

          <div className={styles.formGroup}>
            <label>服务商</label>
            <select
              value={copilotProvider}
              onChange={(e) => {
                setCopilotProvider(e.target.value);
                // Set default model based on provider
                const defaultModels: Record<string, string> = {
                  openai: 'gpt-4',
                  zhipu: 'glm-4',
                  deepseek: 'deepseek-chat',
                  qwen: 'qwen-plus',
                  moonshot: 'moonshot-v1-8k',
                  ollama: 'llama2',
                };
                setCopilotModel(defaultModels[e.target.value] || 'gpt-4');
              }}
            >
              <option value="openai">OpenAI</option>
              <option value="zhipu">智谱 AI (GLM)</option>
              <option value="deepseek">DeepSeek</option>
              <option value="qwen">通义千问</option>
              <option value="moonshot">Moonshot</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="ollama">Ollama (本地部署)</option>
            </select>
          </div>

          <div className={styles.formGroup}>
            <label>API Key {copilotProvider !== 'ollama' && '*'}</label>
            <input
              type="password"
              value={copilotApiKey}
              onChange={(e) => setCopilotApiKey(e.target.value)}
              placeholder={copilotConfig?.api_key_configured ? '••••••••' : '请输入 API Key'}
            />
            <span className={styles.hint}>
              {copilotConfig?.api_key_configured
                ? `当前: ${copilotConfig.api_key_preview}`
                : copilotProvider === 'ollama'
                  ? 'Ollama 无需 API Key'
                  : '必填'}
            </span>
          </div>

          <div className={styles.formGroup}>
            <label>模型</label>
            <select value={copilotModel} onChange={(e) => setCopilotModel(e.target.value)}>
              {copilotProvider === 'openai' && (
                <>
                  <option value="gpt-4">GPT-4</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4o-mini">GPT-4o Mini</option>
                </>
              )}
              {copilotProvider === 'zhipu' && (
                <>
                  <option value="glm-4">GLM-4</option>
                  <option value="glm-4-plus">GLM-4 Plus</option>
                  <option value="glm-4-air">GLM-4 Air</option>
                </>
              )}
              {copilotProvider === 'deepseek' && (
                <>
                  <option value="deepseek-chat">DeepSeek Chat</option>
                  <option value="deepseek-coder">DeepSeek Coder</option>
                </>
              )}
              {copilotProvider === 'qwen' && (
                <>
                  <option value="qwen-turbo">Qwen Turbo</option>
                  <option value="qwen-plus">Qwen Plus</option>
                  <option value="qwen-max">Qwen Max</option>
                </>
              )}
              {copilotProvider === 'moonshot' && (
                <>
                  <option value="moonshot-v1-8k">Moonshot V1 8K</option>
                  <option value="moonshot-v1-32k">Moonshot V1 32K</option>
                </>
              )}
              {copilotProvider === 'anthropic' && (
                <>
                  <option value="claude-3-opus-20240229">Claude 3 Opus</option>
                  <option value="claude-3-sonnet-20240229">Claude 3 Sonnet</option>
                </>
              )}
              {copilotProvider === 'ollama' && (
                <>
                  <option value="llama2">Llama 2</option>
                  <option value="llama3">Llama 3</option>
                  <option value="mistral">Mistral</option>
                </>
              )}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label>API 地址 (可选)</label>
            <input
              type="text"
              value={copilotBaseUrl}
              onChange={(e) => setCopilotBaseUrl(e.target.value)}
              placeholder={copilotProvider === 'ollama' ? 'http://localhost:11434/v1' : '留空使用默认地址'}
            />
            <span className={styles.hint}>
              用于自定义部署或代理地址
            </span>
          </div>

          <button
            className={styles.saveBtn}
            onClick={handleSaveCopilot}
            disabled={isSavingCopilot || (copilotProvider !== 'ollama' && !copilotApiKey && !copilotConfig?.api_key_configured)}
          >
            {isSavingCopilot ? '保存中...' : '保存'}
          </button>
        </div>
      );
    }

    return null;
  }

  // Modal mode - render with overlay

  return (
    <div className={styles.overlay}>
      <div className={styles.panel}>
        <div className={styles.header}>
          <h2>系统设置</h2>
          <button className={styles.closeBtn} onClick={onClose}>×</button>
        </div>

        {error && (
          <div className={styles.errorBanner}>
            {error}
            <button onClick={() => setError(null)}>×</button>
          </div>
        )}

        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${activeTab === 'search' ? styles.active : ''}`}
            onClick={() => setActiveTab('search')}
          >
            搜索引擎
          </button>
          <button
            className={`${styles.tab} ${activeTab === 'email' ? styles.active : ''}`}
            onClick={() => setActiveTab('email')}
          >
            邮件服务
          </button>
          <button
            className={`${styles.tab} ${activeTab === 'copilot' ? styles.active : ''}`}
            onClick={() => setActiveTab('copilot')}
          >
            AI Copilot
          </button>
        </div>

        <div className={styles.content}>
          {renderTabContent()}
        </div>
      </div>
    </div>
  );
};

export default SettingsPanel;
