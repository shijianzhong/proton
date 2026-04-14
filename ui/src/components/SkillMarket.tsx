import React, { useEffect, useState, useRef } from 'react';
import { FiLayers, FiUploadCloud, FiTrash2, FiUsers, FiClock, FiBox, FiSearch, FiX, FiTool, FiDatabase, FiPlus } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../api/client';
import { useToast } from './ToastProvider';
import styles from './SkillMarket.module.css';

export interface SystemTool {
  name: string;
  description: string;
  category: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string | null;
  tags: string[];
  enabled: boolean;
  installed_at: string;
  agent_count: number;
  readme?: string;
  parameters_schema?: Record<string, any>;
  dependencies?: string[];
  _type?: 'skill' | 'system_tool' | 'mcp';
  command?: string;
  args?: string[];
  env?: Record<string, string>;
}

const CATEGORIES = [
  { id: 'all', label: '全部技能' },
  { id: 'search', label: '搜索与研究', tags: ['search', 'web', 'research', 'google', 'bing'] },
  { id: 'data', label: '数据与分析', tags: ['data', 'database', 'excel', 'sql', 'analysis', 'math'] },
  { id: 'dev', label: '开发与工具', tags: ['dev', 'code', 'github', 'shell', 'python', 'terminal', 'api'] },
  { id: 'productivity', label: '效率与办公', tags: ['productivity', 'office', 'pdf', 'mail', 'calendar', 'doc'] },
  { id: 'media', label: '图像与多媒体', tags: ['image', 'video', 'audio', 'media', 'design'] },
  { id: 'other', label: '其他', tags: [] }
];

const SkillMarket: React.FC = () => {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');
  const [activeTab, setActiveTab] = useState<'skills' | 'system' | 'mcp'>('skills');
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [displayCount, setDisplayCount] = useState(20);

  const [mcpModalVisible, setMcpModalVisible] = useState(false);
  const [mcpForm, setMcpForm] = useState({ name: '', command: '', args: '', env: '' });

  const fileInputRef = useRef<HTMLInputElement>(null);
  const { showToast } = useToast();

  const fetchSkills = async () => {
    try {
      setLoading(true);
      // Fetch Python Skills
      const skillsData = await api.listSkills() as Skill[];
      const typedSkills = skillsData.map(s => ({ ...s, _type: 'skill' as const }));

      // Fetch System Tools
      let systemTools: Skill[] = [];
      try {
        const sysToolsResponse = await api.listSystemTools();
        systemTools = sysToolsResponse.tools.map((t: SystemTool) => ({
          id: `sys_${t.name}`,
          name: t.name,
          description: t.description,
          version: '内置',
          author: 'Proton',
          tags: ['system', t.category.toLowerCase()],
          enabled: true,
          installed_at: new Date().toISOString(),
          agent_count: 0,
          _type: 'system_tool' as const
        }));
      } catch (e) {
        console.warn('Failed to fetch system tools', e);
      }

      // Fetch MCP Servers
      let mcpServers: Skill[] = [];
      try {
        const mcpData = await api.listMCPs();
        mcpServers = mcpData.map((m: any) => ({
          id: m.id,
          name: m.name,
          description: m.description || m.command,
          version: m.version,
          author: m.author || 'User',
          tags: m.tags || ['mcp'],
          enabled: m.enabled,
          installed_at: m.installed_at,
          agent_count: m.agent_count || 0,
          command: m.command,
          args: m.args,
          env: m.env,
          _type: 'mcp' as const
        }));
      } catch (e) {
        console.warn('Failed to fetch MCP servers', e);
      }

      // Merge and sort
      const allData = [...typedSkills, ...systemTools, ...mcpServers];
      const sortedData = allData.sort((a, b) => b.agent_count - a.agent_count);
      setSkills(sortedData);
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || err?.message || String(err);
      showToast(errMsg, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, []);

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setUploading(true);
      await api.uploadSkill(file);
      showToast('技能安装成功！', 'success');
      fetchSkills(); // Refresh the list
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || err?.message || String(err);
      showToast(errMsg, 'error');
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = ''; // Reset input
      }
    }
  };

  const handleDelete = async (e: React.MouseEvent, skillId: string, skillName: string, type?: string) => {
    e.stopPropagation();
    if (!window.confirm(`确定要卸载并删除 "${skillName}" 吗？这可能会影响正在使用它的 Agent。`)) {
      return;
    }

    try {
      if (type === 'mcp') {
        await api.deleteMCP(skillId);
      } else {
        await api.uninstallSkill(skillId);
      }
      showToast(`已卸载 ${skillName}`, 'success');
      setSkills(skills.filter((s) => s.id !== skillId));
      if (selectedSkill?.id === skillId) {
        setSelectedSkill(null);
      }
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || err?.message || String(err);
      showToast(errMsg, 'error');
    }
  };

  const handleMcpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mcpForm.name || !mcpForm.command) {
      showToast('名称和启动命令为必填项', 'error');
      return;
    }

    try {
      setUploading(true);
      
      // Parse args and env
      const argsList = mcpForm.args ? mcpForm.args.split('\n').map(s => s.trim()).filter(Boolean) : [];
      
      const envDict: Record<string, string> = {};
      if (mcpForm.env) {
        const lines = mcpForm.env.split('\n');
        lines.forEach(line => {
          const idx = line.indexOf('=');
          if (idx > 0) {
            envDict[line.substring(0, idx).trim()] = line.substring(idx + 1).trim();
          }
        });
      }

      await api.registerMCP({
        name: mcpForm.name,
        command: mcpForm.command,
        args: argsList,
        env: envDict,
        is_global: true
      });
      
      showToast('MCP 服务连接成功！', 'success');
      setMcpModalVisible(false);
      setMcpForm({ name: '', command: '', args: '', env: '' });
      fetchSkills();
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || err?.message || String(err);
      showToast(errMsg, 'error');
    } finally {
      setUploading(false);
    }
  };

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  const filteredSkills = skills.filter(skill => {
    // 1. Filter by Tab (Skill vs System Tool vs MCP)
    if (activeTab === 'skills' && skill._type !== 'skill') return false;
    if (activeTab === 'system' && skill._type !== 'system_tool') return false;
    if (activeTab === 'mcp' && skill._type !== 'mcp') return false;

    // 2. Filter by Search Query
    const matchSearch = skill.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                        skill.description.toLowerCase().includes(searchQuery.toLowerCase());
    
    // 3. Filter by Category (Only applies to Skills tab, system tools have their own basic tags)
    let matchCategory = true;
    if (activeTab === 'skills' && activeCategory !== 'all') {
      const cat = CATEGORIES.find(c => c.id === activeCategory);
      if (cat) {
        if (cat.id === 'other') {
          const allPredefinedTags = CATEGORIES.filter(c => c.id !== 'all' && c.id !== 'other').flatMap(c => c.tags || []);
          matchCategory = !skill.tags?.some(tag => allPredefinedTags.includes(tag.toLowerCase()));
        } else {
          matchCategory = skill.tags?.some(tag => cat.tags?.includes(tag.toLowerCase()));
        }
      }
    }
    
    return matchSearch && matchCategory;
  });

  const displayedSkills = filteredSkills.slice(0, displayCount);

  const handleLoadMore = () => {
    setDisplayCount(prev => prev + 20);
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>技能库 (Skill Market)</h1>
          <p className={styles.description}>
            管理和安装全局的扩展能力，这些能力可以被所有工作流和 Agent 绑定并复用。
          </p>
        </div>
        <div className={styles.actions}>
          {activeTab === 'skills' && (
            <>
              <input
                type="file"
                ref={fileInputRef}
                className={styles.hiddenInput}
                accept=".zip,.skill"
                onChange={handleFileChange}
              />
              <button
                className={styles.uploadBtn}
                onClick={handleUploadClick}
                disabled={uploading}
              >
                <FiUploadCloud size={16} />
                {uploading ? '安装中...' : '上传并安装技能'}
              </button>
            </>
          )}
          {activeTab === 'mcp' && (
            <button
              className={styles.uploadBtn}
              onClick={() => setMcpModalVisible(true)}
              style={{ background: '#8b5cf6' }}
            >
              <FiPlus size={16} />
              连接 MCP 服务
            </button>
          )}
        </div>
      </header>

      <div className={styles.tabsContainer}>
        <div className={styles.tabs}>
          <button 
            className={`${styles.tab} ${activeTab === 'skills' ? styles.activeTab : ''}`}
            onClick={() => { setActiveTab('skills'); setActiveCategory('all'); setDisplayCount(20); }}
          >
            <FiLayers /> 技能包 (Skills)
          </button>
          <button 
            className={`${styles.tab} ${activeTab === 'mcp' ? styles.activeTab : ''}`}
            onClick={() => { setActiveTab('mcp'); setDisplayCount(20); }}
          >
            <FiDatabase /> MCP 服务 (MCP Servers)
          </button>
          <button 
            className={`${styles.tab} ${activeTab === 'system' ? styles.activeTab : ''}`}
            onClick={() => { setActiveTab('system'); setDisplayCount(20); }}
          >
            <FiTool /> 系统底层能力 (System Tools)
          </button>
        </div>
      </div>

      <div className={styles.layout}>
        {activeTab === 'skills' && (
          <aside className={styles.sidebar}>
            {CATEGORIES.map(cat => (
              <button 
                key={cat.id} 
                className={`${styles.categoryBtn} ${activeCategory === cat.id ? styles.active : ''}`}
                onClick={() => setActiveCategory(cat.id)}
              >
                {cat.label}
              </button>
            ))}
          </aside>
        )}

        <main className={styles.mainContent}>
          <div className={styles.toolbar}>
            <div className={styles.searchBox}>
              <FiSearch />
              <input 
                type="text" 
                placeholder="搜索技能名称或描述..." 
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className={styles.searchInput}
              />
            </div>
          </div>

          {loading ? (
            <div className={styles.loading}>加载中...</div>
          ) : filteredSkills.length === 0 ? (
            <div className={styles.emptyState}>
              <FiBox className={styles.emptyIcon} />
              <h3>未找到相关技能</h3>
              <p>请尝试更改分类或搜索关键词，或者点击右上角安装新技能</p>
            </div>
          ) : (
            <>
              <div className={styles.grid}>
                {displayedSkills.map((skill) => (
                  <div 
                    key={skill.id} 
                    className={styles.card} 
                    onClick={() => setSelectedSkill(skill)}
                  >
                    <div className={styles.cardHeader}>
                      <div className={styles.cardTitle}>
                      <div className={styles.iconWrapper} style={skill._type === 'system_tool' ? { background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' } : skill._type === 'mcp' ? { background: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' } : {}}>
                        {skill._type === 'system_tool' ? <FiTool /> : skill._type === 'mcp' ? <FiDatabase /> : <FiLayers />}
                      </div>
                      <div>
                        <h3 className={styles.name}>{skill.name}</h3>
                        <span className={styles.version} style={skill._type === 'system_tool' ? { background: '#d1fae5', color: '#047857' } : skill._type === 'mcp' ? { background: '#ede9fe', color: '#6d28d9' } : {}}>
                          {skill._type === 'system_tool' ? '内置工具' : skill._type === 'mcp' ? 'MCP 服务' : `v${skill.version}`}
                        </span>
                      </div>
                    </div>
                    {skill._type !== 'system_tool' && (
                      <button
                        className={styles.deleteBtn}
                        onClick={(e) => handleDelete(e, skill.id, skill.name, skill._type)}
                        title="卸载"
                      >
                        <FiTrash2 size={16} />
                      </button>
                    )}
                    </div>

                    {skill.tags && skill.tags.length > 0 && (
                      <div className={styles.tags}>
                        {skill.tags.map((tag, index) => (
                          <span key={index} className={styles.tag}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}

                    <p className={styles.cardDesc}>{skill.description}</p>

                    <div className={styles.cardFooter}>
                      <div className={styles.stat} title="已被多少个 Agent 绑定">
                        <FiUsers />
                        <span>{skill.agent_count} 绑定</span>
                      </div>
                      <div className={styles.stat} title="安装时间">
                        <FiClock />
                        <span className={styles.date}>{formatDate(skill.installed_at)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              
              {filteredSkills.length > displayCount && (
                <div className={styles.loadMoreContainer}>
                  <button className={styles.loadMoreBtn} onClick={handleLoadMore}>
                    加载更多
                  </button>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {selectedSkill && (
        <div className={styles.modalOverlay} onClick={() => setSelectedSkill(null)}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div className={styles.modalTitleGroup}>
                <div className={styles.iconWrapper} style={selectedSkill._type === 'system_tool' ? { background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' } : selectedSkill._type === 'mcp' ? { background: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' } : {}}>
                  {selectedSkill._type === 'system_tool' ? <FiTool /> : selectedSkill._type === 'mcp' ? <FiDatabase /> : <FiLayers />}
                </div>
                <div>
                  <h2 className={styles.modalTitle}>{selectedSkill.name}</h2>
                  <span className={styles.version} style={{ marginTop: '4px', display: 'inline-block', ...(selectedSkill._type === 'system_tool' ? { background: '#d1fae5', color: '#047857' } : selectedSkill._type === 'mcp' ? { background: '#ede9fe', color: '#6d28d9' } : {}) }}>
                    {selectedSkill._type === 'system_tool' ? '官方内置能力' : selectedSkill._type === 'mcp' ? 'MCP 服务' : `v${selectedSkill.version}`}
                  </span>
                </div>
              </div>
              <button className={styles.closeBtn} onClick={() => setSelectedSkill(null)}>
                <FiX size={20} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.detailSection}>
                <span className={styles.detailLabel}>{selectedSkill._type === 'mcp' ? '服务描述' : '技能描述'}</span>
                <p className={styles.detailText}>{selectedSkill.description}</p>
              </div>

              {selectedSkill._type === 'mcp' && (
                <>
                  <div className={styles.detailSection}>
                    <span className={styles.detailLabel}>启动命令 (Command)</span>
                    <pre className={styles.codeBlock}>{selectedSkill.command}</pre>
                  </div>
                  {selectedSkill.args && selectedSkill.args.length > 0 && (
                    <div className={styles.detailSection}>
                      <span className={styles.detailLabel}>启动参数 (Args)</span>
                      <pre className={styles.codeBlock}>{selectedSkill.args.join('\n')}</pre>
                    </div>
                  )}
                  {selectedSkill.env && Object.keys(selectedSkill.env).length > 0 && (
                    <div className={styles.detailSection}>
                      <span className={styles.detailLabel}>环境变量 (Env)</span>
                      <pre className={styles.codeBlock}>
                        {Object.entries(selectedSkill.env).map(([k, v]) => `${k}=${v}`).join('\n')}
                      </pre>
                    </div>
                  )}
                </>
              )}

              {selectedSkill.readme && (
                <div className={styles.detailSection}>
                  <span className={styles.detailLabel}>SKILL.md / 使用文档</span>
                  <div className={styles.markdownContainer}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {selectedSkill.readme}
                    </ReactMarkdown>
                  </div>
                </div>
              )}

              {selectedSkill.parameters_schema && Object.keys(selectedSkill.parameters_schema).length > 0 && (
                <div className={styles.detailSection}>
                  <span className={styles.detailLabel}>参数 Schema</span>
                  <pre className={styles.codeBlock}>
                    {JSON.stringify(selectedSkill.parameters_schema, null, 2)}
                  </pre>
                </div>
              )}

              {selectedSkill.dependencies && selectedSkill.dependencies.length > 0 && (
                <div className={styles.detailSection}>
                  <span className={styles.detailLabel}>系统依赖</span>
                  <div className={styles.tags} style={{ marginBottom: 0 }}>
                    {selectedSkill.dependencies.map((dep, index) => (
                      <span key={index} className={styles.tag}>{dep}</span>
                    ))}
                  </div>
                </div>
              )}
              
              <div className={styles.detailSection}>
                <span className={styles.detailLabel}>标签分类</span>
                <div className={styles.tags} style={{ marginBottom: 0 }}>
                  {selectedSkill.tags && selectedSkill.tags.length > 0 ? (
                    selectedSkill.tags.map((tag, index) => (
                      <span key={index} className={styles.tag}>{tag}</span>
                    ))
                  ) : (
                    <span className={styles.detailText} style={{ color: '#888' }}>暂无标签</span>
                  )}
                </div>
              </div>

              <div className={styles.detailSection}>
                <span className={styles.detailLabel}>作者信息</span>
                <p className={styles.detailText}>{selectedSkill.author || 'Proton Community'}</p>
              </div>

              <div className={styles.detailSection}>
                <span className={styles.detailLabel}>使用情况</span>
                <p className={styles.detailText}>已被 {selectedSkill.agent_count} 个工作流/Agent 绑定使用</p>
              </div>

              <div className={styles.detailSection}>
                <span className={styles.detailLabel}>安装时间</span>
                <p className={styles.detailText}>{formatDate(selectedSkill.installed_at)}</p>
              </div>
            </div>
          </div>
        </div>
      )}
      {mcpModalVisible && (
        <div className={styles.modalOverlay} onClick={() => setMcpModalVisible(false)}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div className={styles.modalTitleGroup}>
                <div className={styles.iconWrapper} style={{ background: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' }}>
                  <FiDatabase />
                </div>
                <h2 className={styles.modalTitle}>连接全局 MCP 服务</h2>
              </div>
              <button className={styles.closeBtn} onClick={() => setMcpModalVisible(false)}>
                <FiX size={20} />
              </button>
            </div>
            <form onSubmit={handleMcpSubmit}>
              <div className={styles.modalBody}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>服务名称 <span className={styles.required}>*</span></label>
                  <input
                    type="text"
                    className={styles.formInput}
                    placeholder="例如: github-mcp"
                    value={mcpForm.name}
                    onChange={e => setMcpForm({ ...mcpForm, name: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>启动命令 (Command) <span className={styles.required}>*</span></label>
                  <input
                    type="text"
                    className={styles.formInput}
                    placeholder="例如: npx"
                    value={mcpForm.command}
                    onChange={e => setMcpForm({ ...mcpForm, command: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>启动参数 (Args)</label>
                  <textarea
                    className={styles.formTextarea}
                    placeholder="-y&#10;@modelcontextprotocol/server-github"
                    value={mcpForm.args}
                    onChange={e => setMcpForm({ ...mcpForm, args: e.target.value })}
                    rows={3}
                  />
                  <span className={styles.formHint}>每行一个参数</span>
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>环境变量 (Env)</label>
                  <textarea
                    className={styles.formTextarea}
                    placeholder="GITHUB_TOKEN=ghp_xxxxxxxx&#10;OTHER_VAR=value"
                    value={mcpForm.env}
                    onChange={e => setMcpForm({ ...mcpForm, env: e.target.value })}
                    rows={3}
                  />
                  <span className={styles.formHint}>每行一个，格式为 KEY=VALUE</span>
                </div>
              </div>
              <div className={styles.modalFooter}>
                <button type="button" className={styles.cancelBtn} onClick={() => setMcpModalVisible(false)}>
                  取消
                </button>
                <button type="submit" className={styles.submitBtn} disabled={uploading}>
                  {uploading ? '连接中...' : '确认连接'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default SkillMarket;