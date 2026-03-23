import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import styles from './PortalList.module.css';
import { useToast } from './ToastProvider';

/* ------------------------------------------------------------------ */
/*  Types                                                               */
/* ------------------------------------------------------------------ */

export interface Portal {
  id: string;
  name: string;
  description: string;
  workflow_ids: string[];
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
  memory_enabled: boolean;
  api_key_access?: string;
  public: boolean;
  created_at: string;
  updated_at: string;
}

interface Workflow {
  id: string;
  name: string;
  description: string;
  state: string;
  agent_count: number;
}

interface PortalListProps {
  onOpenChat: (portal: Portal) => void;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                             */
/* ------------------------------------------------------------------ */

const MODELS: Record<string, string[]> = {
  openai:    ['gpt-4o', 'gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  deepseek:  ['deepseek-chat', 'deepseek-coder'],
  zhipu:     ['glm-4', 'glm-4-flash', 'glm-3-turbo'],
  qwen:      ['qwen-plus', 'qwen-max', 'qwen-turbo'],
  moonshot:  ['moonshot-v1-8k', 'moonshot-v1-32k'],
  anthropic: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229'],
  ollama:    ['llama3', 'mistral', 'qwen2'],
};

const PROVIDERS = Object.keys(MODELS);

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/* ------------------------------------------------------------------ */
/*  Create / Edit Modal                                                 */
/* ------------------------------------------------------------------ */

interface FormState {
  name: string;
  description: string;
  workflow_ids: string[];
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
  memory_enabled: boolean;
}

const defaultForm = (): FormState => ({
  name: '',
  description: '',
  workflow_ids: [],
  provider: 'openai',
  model: 'gpt-4o',
  api_key: '',
  base_url: '',
  memory_enabled: true,
});

interface PortalModalProps {
  portal: Portal | null;           // null = create mode
  workflows: Workflow[];
  onClose: () => void;
  onSave: (data: FormState, id?: string) => Promise<void>;
}

const PortalModal: React.FC<PortalModalProps> = ({ portal, workflows, onClose, onSave }) => {
  const toast = useToast();
  const [form, setForm] = useState<FormState>(() =>
    portal
      ? {
          name: portal.name,
          description: portal.description,
          workflow_ids: portal.workflow_ids,
          provider: portal.provider,
          model: portal.model,
          api_key: portal.api_key ?? '',
          base_url: portal.base_url ?? '',
          memory_enabled: portal.memory_enabled,
        }
      : defaultForm()
  );
  const [saving, setSaving] = useState(false);

  const set = (k: keyof FormState, v: any) => setForm(f => ({ ...f, [k]: v }));

  const toggleWf = (id: string) => {
    set(
      'workflow_ids',
      form.workflow_ids.includes(id)
        ? form.workflow_ids.filter(x => x !== id)
        : [...form.workflow_ids, id]
    );
  };

  const handleSave = async () => {
    if (!form.name.trim()) { toast.warning('请填写超级入口名称'); return; }
    if (form.workflow_ids.length === 0) { toast.warning('请至少选择一个工作流'); return; }
    setSaving(true);
    try {
      await onSave(form, portal?.id);
      onClose();
    } catch (e: any) {
      toast.error('保存失败', e?.message);
    } finally {
      setSaving(false);
    }
  };

  const modelOptions = MODELS[form.provider] ?? [];

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        {/* Title */}
        <div>
          <div className={styles.modalTitle}>
            {portal ? '编辑超级入口' : '新建超级入口'}
          </div>
          <div className={styles.modalSubtitle}>
            超级入口将多个工作流聚合为一个智能统一入口，自动理解意图并路由
          </div>
        </div>

        {/* Basic info */}
        <div className={styles.sectionDivider}>基本信息</div>

        <div className={styles.formGroup}>
          <label className={styles.label}>名称 *</label>
          <input
            className={styles.input}
            placeholder="如：企业智能助手"
            value={form.name}
            onChange={e => set('name', e.target.value)}
          />
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>描述</label>
          <textarea
            className={styles.textarea}
            placeholder="描述这个超级入口的用途..."
            value={form.description}
            onChange={e => set('description', e.target.value)}
          />
        </div>

        {/* Workflow selection */}
        <div className={styles.sectionDivider}>绑定工作流 *</div>

        <div className={styles.formGroup}>
          <label className={styles.label}>
            选择工作流（已选 {form.workflow_ids.length} 个）
          </label>
          <div className={styles.wfList}>
            {workflows.length === 0 ? (
              <div className={styles.wfEmpty}>暂无已发布的工作流</div>
            ) : (
              workflows.map(wf => {
                const checked = form.workflow_ids.includes(wf.id);
                return (
                  <div
                    key={wf.id}
                    className={`${styles.wfItem} ${checked ? styles.wfItemChecked : ''}`}
                    onClick={() => toggleWf(wf.id)}
                  >
                    <input
                      type="checkbox"
                      className={styles.wfCheckbox}
                      checked={checked}
                      onChange={() => {}}
                    />
                    <div className={styles.wfItemInfo}>
                      <div className={styles.wfItemName}>{wf.name}</div>
                      {wf.description && (
                        <div className={styles.wfItemDesc}>{wf.description}</div>
                      )}
                    </div>
                    <div className={styles.wfItemMeta}>{wf.agent_count} 个 agent</div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* LLM config */}
        <div className={styles.sectionDivider}>LLM 配置</div>

        <div className={styles.row2}>
          <div className={styles.formGroup}>
            <label className={styles.label}>提供商</label>
            <select
              className={styles.select}
              value={form.provider}
              onChange={e => {
                const p = e.target.value;
                set('provider', p);
                set('model', MODELS[p]?.[0] ?? '');
              }}
            >
              {PROVIDERS.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className={styles.formGroup}>
            <label className={styles.label}>模型</label>
            <select
              className={styles.select}
              value={form.model}
              onChange={e => set('model', e.target.value)}
            >
              {modelOptions.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>API Key（留空则读环境变量）</label>
          <input
            className={styles.input}
            type="password"
            placeholder="sk-..."
            value={form.api_key}
            onChange={e => set('api_key', e.target.value)}
          />
        </div>

        {(form.provider === 'ollama' || form.provider === 'zhipu' || form.provider === 'deepseek' || form.base_url) && (
          <div className={styles.formGroup}>
            <label className={styles.label}>Base URL（自定义接口地址）</label>
            <input
              className={styles.input}
              placeholder="https://api.example.com/v1"
              value={form.base_url}
              onChange={e => set('base_url', e.target.value)}
            />
          </div>
        )}

        {/* Options */}
        <div className={styles.sectionDivider}>功能选项</div>

        <div
          className={styles.wfItem}
          style={{ border: '1px solid var(--color-secondary)', borderRadius: 8 }}
          onClick={() => set('memory_enabled', !form.memory_enabled)}
        >
          <input
            type="checkbox"
            className={styles.wfCheckbox}
            checked={form.memory_enabled}
            onChange={() => {}}
          />
          <div className={styles.wfItemInfo}>
            <div className={styles.wfItemName}>启用长期记忆</div>
            <div className={styles.wfItemDesc}>跨会话记住用户偏好，提升个性化体验</div>
          </div>
        </div>

        {/* Footer */}
        <div className={styles.modalFooter}>
          <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={onClose}>
            取消
          </button>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <span className={styles.spinner} /> : null}
            {saving ? '保存中…' : portal ? '保存修改' : '创建入口'}
          </button>
        </div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Access Key Modal                                                    */
/* ------------------------------------------------------------------ */

const KeyModal: React.FC<{ portal: Portal; onClose: () => void }> = ({ portal, onClose }) => {
  const [copied, setCopied] = useState(false);
  const endpoint = `${window.location.protocol}//${window.location.hostname}:8000/api/portals/access/${portal.api_key_access}/chat`;

  const copy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} style={{ maxWidth: 500 }} onClick={e => e.stopPropagation()}>
        <div className={styles.modalTitle}>🔑 访问密钥</div>
        <div className={styles.modalSubtitle}>
          使用以下密钥通过 API 访问「{portal.name}」
        </div>

        <div className={styles.sectionDivider}>Portal ID</div>
        <div className={styles.keyBox}>
          <span>{portal.id}</span>
          <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => copy(portal.id)}>复制</button>
        </div>

        <div className={styles.sectionDivider}>Access Key</div>
        <div className={styles.keyBox}>
          <span>{portal.api_key_access ?? '（未设置）'}</span>
          {portal.api_key_access && (
            <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => copy(portal.api_key_access!)}>
              {copied ? '✓' : '复制'}
            </button>
          )}
        </div>

        <div className={styles.sectionDivider}>对外接口地址</div>
        <div className={styles.keyBox} style={{ fontSize: '0.75rem' }}>
          <span style={{ wordBreak: 'break-all' }}>POST {endpoint}</span>
          <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => copy(endpoint)}>复制</button>
        </div>

        <div className={styles.formGroup} style={{ background: 'rgba(96,165,250,0.08)', borderRadius: 8, padding: '10px 14px' }}>
          <div style={{ fontSize: '0.8rem', color: '#93c5fd', lineHeight: 1.6 }}>
            <b>请求示例：</b><br />
            <code style={{ fontSize: '0.75rem', color: '#bfdbfe' }}>
              {`POST ${endpoint}\n{\n  "session_id": "xxx",\n  "message": "你好",\n  "user_id": "alice"\n}`}
            </code>
          </div>
        </div>

        <div className={styles.modalFooter}>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Main PortalList Component                                           */
/* ------------------------------------------------------------------ */

const PortalList: React.FC<PortalListProps> = ({ onOpenChat }) => {
  const [portals, setPortals] = useState<Portal[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);

  // Modal states
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Portal | null>(null);
  const [keyTarget, setKeyTarget] = useState<Portal | null>(null);

  useEffect(() => {
    loadAll();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [ps, wfs] = await Promise.all([
        (api as any).listPortals() as Promise<Portal[]>,
        api.listWorkflows(),
      ]);
      setPortals(ps);
      setWorkflows(wfs);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (form: FormState, id?: string) => {
    const payload = {
      name: form.name,
      description: form.description,
      workflow_ids: form.workflow_ids,
      provider: form.provider,
      model: form.model,
      api_key: form.api_key || undefined,
      base_url: form.base_url || undefined,
      memory_enabled: form.memory_enabled,
    };

    if (id) {
      await (api as any).updatePortal(id, payload);
    } else {
      await (api as any).createPortal(payload);
    }
    await loadAll();
  };

  const handleDelete = async (portal: Portal) => {
    if (!confirm(`确认删除超级入口「${portal.name}」？`)) return;
    await (api as any).deletePortal(portal.id);
    await loadAll();
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h2>超级入口</h2>
          <p>将多个工作流聚合为一个智能统一入口，具备意图理解、长期记忆和结果综合能力</p>
        </div>
        <button
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={() => setCreateOpen(true)}
        >
          ＋ 新建超级入口
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div className={styles.empty}>
          <div className={styles.spinner} style={{ width: 28, height: 28, borderWidth: 3 }} />
        </div>
      ) : portals.length === 0 ? (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>🚀</div>
          <h3>还没有超级入口</h3>
          <p>创建一个超级入口，把多个工作流聚合成一个智能助手，支持意图路由和跨会话记忆</p>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={() => setCreateOpen(true)}
          >
            ＋ 新建超级入口
          </button>
        </div>
      ) : (
        <div className={styles.grid}>
          {portals.map(portal => {
            const boundWfs = workflows.filter(w => portal.workflow_ids.includes(w.id));
            return (
              <div key={portal.id} className={styles.card}>
                <div className={styles.cardHeader}>
                  <div className={styles.cardIcon}>🧠</div>
                  <div className={styles.cardTitle}>
                    <h3>{portal.name}</h3>
                    <p>{portal.description || '无描述'}</p>
                  </div>
                </div>

                {/* Badges */}
                <div className={styles.cardMeta}>
                  <span className={`${styles.badge} ${styles.badgeBlue}`}>
                    {portal.provider} / {portal.model}
                  </span>
                  <span className={`${styles.badge} ${portal.memory_enabled ? styles.badgeGreen : styles.badgeGray}`}>
                    {portal.memory_enabled ? '记忆开启' : '记忆关闭'}
                  </span>
                  <span className={styles.wfCount}>
                    绑定 {portal.workflow_ids.length} 个工作流
                  </span>
                </div>

                {/* Bound workflow tags */}
                {boundWfs.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {boundWfs.map(wf => (
                      <span key={wf.id} className={`${styles.badge} ${styles.badgeGray}`}>
                        {wf.name}
                      </span>
                    ))}
                    {portal.workflow_ids.length > boundWfs.length && (
                      <span className={`${styles.badge} ${styles.badgeGray}`}>
                        +{portal.workflow_ids.length - boundWfs.length} 未发布
                      </span>
                    )}
                  </div>
                )}

                <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  创建于 {fmtDate(portal.created_at)}
                </div>

                {/* Actions */}
                <div className={styles.cardActions}>
                  <button
                    className={`${styles.btn} ${styles.btnPrimary}`}
                    style={{ flex: 1 }}
                    onClick={() => onOpenChat(portal)}
                  >
                    💬 打开对话
                  </button>
                  <button
                    className={`${styles.btn} ${styles.btnSecondary}`}
                    onClick={() => setEditTarget(portal)}
                  >
                    编辑
                  </button>
                  <button
                    className={`${styles.btn} ${styles.btnGhost}`}
                    title="查看访问密钥"
                    onClick={() => setKeyTarget(portal)}
                  >
                    🔑
                  </button>
                  <button
                    className={`${styles.btn} ${styles.btnDanger}`}
                    title="删除"
                    onClick={() => handleDelete(portal)}
                  >
                    🗑
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Create modal */}
      {createOpen && (
        <PortalModal
          portal={null}
          workflows={workflows}
          onClose={() => setCreateOpen(false)}
          onSave={handleSave}
        />
      )}

      {/* Edit modal */}
      {editTarget && (
        <PortalModal
          portal={editTarget}
          workflows={workflows}
          onClose={() => setEditTarget(null)}
          onSave={handleSave}
        />
      )}

      {/* Key modal */}
      {keyTarget && (
        <KeyModal portal={keyTarget} onClose={() => setKeyTarget(null)} />
      )}
    </div>
  );
};

export default PortalList;
