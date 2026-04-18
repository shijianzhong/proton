import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api, type ArtifactTransferRecommendation } from '../api/client';
import styles from './PortalList.module.css';
import { useToast } from './ToastProvider';

/* ------------------------------------------------------------------ */
/*  Types                                                               */
/* ------------------------------------------------------------------ */

export interface Portal {
  id: string;
  name: string;
  description: string;
  is_default?: boolean;
  workflow_ids: string[];
  child_portal_ids?: string[];
  auto_discover_child_portals?: boolean;
  disabled_child_portal_ids?: string[];
  max_portals_per_request?: number;
  max_workflows_per_request?: number;
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
  memory_enabled: boolean;
  global_memory_enabled?: boolean;
  memory_provider?: string;
  mempalace_palace_path?: string;
  mempalace_wing_strategy?: string;
  mempalace_default_room?: string;
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
  zhipu:     ['glm-4', 'glm-4-flash', 'glm-4.5-air', 'glm-3-turbo'],
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
  is_default: boolean;
  workflow_ids: string[];
  child_portal_ids: string[];
  auto_discover_child_portals: boolean;
  disabled_child_portal_ids: string[];
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
  memory_enabled: boolean;
  global_memory_enabled: boolean;
  memory_provider: string;
  mempalace_palace_path: string;
  mempalace_wing_strategy: string;
  mempalace_default_room: string;
}

const defaultForm = (): FormState => ({
  name: '',
  description: '',
  is_default: false,
  workflow_ids: [],
  child_portal_ids: [],
  auto_discover_child_portals: true,
  disabled_child_portal_ids: [],
  provider: 'openai',
  model: 'gpt-4o',
  api_key: '',
  base_url: '',
  memory_enabled: true,
  global_memory_enabled: false,
  memory_provider: 'mempalace',
  mempalace_palace_path: 'proton_global_memory',
  mempalace_wing_strategy: 'per_user',
  mempalace_default_room: 'general',
});

interface PortalModalProps {
  portal: Portal | null;           // null = create mode
  portals: Portal[];
  workflows: Workflow[];
  onClose: () => void;
  onSave: (data: FormState, id?: string) => Promise<void>;
}

const WorkflowSelector = React.memo(function WorkflowSelector({
  workflows,
  selectedIds,
  onToggle,
}: {
  workflows: Workflow[];
  selectedIds: string[];
  onToggle: (id: string) => void;
}) {
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  return (
    <div className={styles.wfList}>
      {workflows.length === 0 ? (
        <div className={styles.wfEmpty}>暂无已发布的工作流</div>
      ) : (
        workflows.map(wf => {
          const checked = selected.has(wf.id);
          return (
            <div
              key={wf.id}
              className={`${styles.wfItem} ${checked ? styles.wfItemChecked : ''}`}
              onClick={() => onToggle(wf.id)}
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
  );
});

const DisabledPortalSelector = React.memo(function DisabledPortalSelector({
  portals,
  selectedIds,
  onToggle,
}: {
  portals: Portal[];
  selectedIds: string[];
  onToggle: (id: string) => void;
}) {
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  return (
    <div className={styles.wfList}>
      {portals.length === 0 ? (
        <div className={styles.wfEmpty}>暂无可排除的子 Portal</div>
      ) : (
        portals.map(p => {
          const checked = selected.has(p.id);
          return (
            <div
              key={p.id}
              className={`${styles.wfItem} ${checked ? styles.wfItemChecked : ''}`}
              onClick={() => onToggle(p.id)}
            >
              <input
                type="checkbox"
                className={styles.wfCheckbox}
                checked={checked}
                onChange={() => {}}
              />
              <div className={styles.wfItemInfo}>
                <div className={styles.wfItemName}>{p.name}</div>
                {p.description && <div className={styles.wfItemDesc}>{p.description}</div>}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
});

const PortalModal: React.FC<PortalModalProps> = ({ portal, portals, workflows, onClose, onSave }) => {
  const toast = useToast();
  const [form, setForm] = useState<FormState>(() =>
    portal
      ? {
          name: portal.name,
          description: portal.description,
          is_default: !!portal.is_default,
          workflow_ids: portal.workflow_ids,
          child_portal_ids: portal.child_portal_ids ?? [],
          auto_discover_child_portals: portal.auto_discover_child_portals ?? true,
          disabled_child_portal_ids: portal.disabled_child_portal_ids ?? [],
          provider: portal.provider,
          model: portal.model,
          api_key: portal.api_key ?? '',
          base_url: portal.base_url ?? '',
          memory_enabled: portal.memory_enabled,
          global_memory_enabled: portal.global_memory_enabled ?? false,
          memory_provider: portal.memory_provider ?? 'mempalace',
          mempalace_palace_path: portal.mempalace_palace_path ?? 'proton_global_memory',
          mempalace_wing_strategy: portal.mempalace_wing_strategy ?? 'per_user',
          mempalace_default_room: portal.mempalace_default_room ?? 'general',
        }
      : defaultForm()
  );
  const [saving, setSaving] = useState(false);

  const set = (k: keyof FormState, v: any) => setForm(f => ({ ...f, [k]: v }));

  const toggleWf = useCallback((id: string) => {
    setForm(f => ({
      ...f,
      workflow_ids: f.workflow_ids.includes(id)
        ? f.workflow_ids.filter(x => x !== id)
        : [...f.workflow_ids, id],
    }));
  }, []);

  const toggleDisabledPortal = useCallback((id: string) => {
    setForm(f => ({
      ...f,
      disabled_child_portal_ids: f.disabled_child_portal_ids.includes(id)
        ? f.disabled_child_portal_ids.filter(x => x !== id)
        : [...f.disabled_child_portal_ids, id],
    }));
  }, []);

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
  const selectableChildPortals = useMemo(
    () => portals.filter(p => !p.is_default && p.id !== portal?.id),
    [portals, portal?.id]
  );

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
          <WorkflowSelector
            workflows={workflows}
            selectedIds={form.workflow_ids}
            onToggle={toggleWf}
          />
        </div>

        {form.is_default && (
          <>
            <div className={styles.sectionDivider}>Portal 分层路由</div>
            <div
              className={styles.wfItem}
              style={{ border: '1px solid var(--color-secondary)', borderRadius: 8 }}
              onClick={() => set('auto_discover_child_portals', !form.auto_discover_child_portals)}
            >
              <input
                type="checkbox"
                className={styles.wfCheckbox}
                checked={form.auto_discover_child_portals}
                onChange={() => {}}
              />
              <div className={styles.wfItemInfo}>
                <div className={styles.wfItemName}>自动发现子 Portal</div>
                <div className={styles.wfItemDesc}>Root 会自动将非默认 Portal 作为一级路由候选</div>
              </div>
            </div>

            {form.auto_discover_child_portals && (
              <div className={styles.formGroup} style={{ marginTop: 10 }}>
                <label className={styles.label}>
                  排除/禁用列表（已排除 {form.disabled_child_portal_ids.length} 个）
                </label>
                <DisabledPortalSelector
                  portals={selectableChildPortals}
                  selectedIds={form.disabled_child_portal_ids}
                  onToggle={toggleDisabledPortal}
                />
              </div>
            )}
          </>
        )}

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

        <div
          className={styles.wfItem}
          style={{ border: '1px solid var(--color-secondary)', borderRadius: 8, marginTop: 10 }}
          onClick={() => set('global_memory_enabled', !form.global_memory_enabled)}
        >
          <input
            type="checkbox"
            className={styles.wfCheckbox}
            checked={form.global_memory_enabled}
            onChange={() => {}}
          />
          <div className={styles.wfItemInfo}>
            <div className={styles.wfItemName}>启用跨入口共享记忆</div>
            <div className={styles.wfItemDesc}>同一用户在其他超级入口的记忆将参与检索</div>
          </div>
        </div>

        {form.memory_enabled && (
          <>
            <div className={styles.sectionDivider}>长期记忆提供商配置</div>
            
            <div className={styles.formGroup}>
              <label className={styles.label}>提供商</label>
              <select
                className={styles.select}
                value={form.memory_provider}
                onChange={e => set('memory_provider', e.target.value)}
              >
                <option value="mempalace">MemPalace（MCP生态空间记忆架构）</option>
              </select>
            </div>

            {form.memory_provider === 'mempalace' && (
              <>
                <div className={styles.formGroup}>
                  <label className={styles.label}>记忆宫殿路径 (Palace Path)</label>
                  <input
                    className={styles.input}
                    placeholder="如：proton_global_memory"
                    value={form.mempalace_palace_path}
                    onChange={e => set('mempalace_palace_path', e.target.value)}
                  />
                </div>
                <div className={styles.row2}>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Wing 分区策略</label>
                    <select
                      className={styles.select}
                      value={form.mempalace_wing_strategy}
                      onChange={e => set('mempalace_wing_strategy', e.target.value)}
                    >
                      <option value="per_user">按 User ID 隔离 (推荐)</option>
                      <option value="per_portal">按 Portal ID 隔离</option>
                      <option value="shared">全局共享 (shared_wing)</option>
                    </select>
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>默认 Room</label>
                    <input
                      className={styles.input}
                      placeholder="如：general"
                      value={form.mempalace_default_room}
                      onChange={e => set('mempalace_default_room', e.target.value)}
                    />
                  </div>
                </div>
              </>
            )}
          </>
        )}

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

const TransferRecommendationModal: React.FC<{
  portal: Portal;
  loading: boolean;
  items: ArtifactTransferRecommendation[];
  onClose: () => void;
}> = ({ portal, loading, items, onClose }) => {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [targetAgentId, setTargetAgentId] = useState('');
  const [showDraft, setShowDraft] = useState(false);
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle');

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedItems = useMemo(
    () => items.filter((it) => selected.has(it.candidate_id)),
    [items, selected]
  );
  const draftActions = useMemo(
    () =>
      selectedItems.map((it) => ({
        action: 'bind_skill_to_agent',
        candidate_id: it.candidate_id,
        materialized_skill_id: it.materialized_skill_id || null,
        required_input: {
          target_agent_id: targetAgentId || '<待填写>',
        },
        endpoint: it.materialized_skill_id
          ? `/api/skills/${it.materialized_skill_id}/bind/{agent_id}`
          : '/api/artifacts/candidates/{candidate_id}/approve -> /api/skills/{skill_id}/bind/{agent_id}',
        note: it.materialized_skill_id
          ? '已有 materialized skill，可直接绑定'
          : '候选尚未物化，需先审批物化再绑定',
      })),
    [selectedItems, targetAgentId]
  );
  const draftPayload = useMemo(
    () => ({ target_portal_id: portal.id, actions: draftActions }),
    [portal.id, draftActions]
  );
  const draftText = useMemo(() => JSON.stringify(draftPayload, null, 2), [draftPayload]);

  const toggle = (id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const copyDraft = async () => {
    if (selectedItems.length === 0) return;
    setCopyStatus('idle');
    setShowDraft(true);
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(draftText);
      } else {
        const ta = document.createElement('textarea');
        ta.value = draftText;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopyStatus('copied');
      window.setTimeout(() => setCopyStatus('idle'), 1400);
    } catch (e) {
      console.error(e);
      setCopyStatus('failed');
      window.setTimeout(() => setCopyStatus('idle'), 1800);
    }
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} style={{ maxWidth: 760 }} onClick={e => e.stopPropagation()}>
        <div className={styles.modalTitle}>🔄 跨 Portal 技能迁移建议</div>
        <div className={styles.modalSubtitle}>
          目标入口：{portal.name}（仅推荐，不自动安装）
        </div>

        {loading ? (
          <div className={styles.empty} style={{ minHeight: 180 }}>
            <div className={styles.spinner} style={{ width: 26, height: 26, borderWidth: 3 }} />
          </div>
        ) : items.length === 0 ? (
          <div className={styles.empty} style={{ minHeight: 180 }}>
            <div className={styles.emptyIcon}>🧩</div>
            <h3>暂无可迁移技能</h3>
            <p>当前没有满足阈值的候选技能，可稍后重试。</p>
          </div>
        ) : (
          <div className={styles.wfList}>
            {items.map((item) => (
              <div key={item.candidate_id} className={styles.wfItem} onClick={() => toggle(item.candidate_id)}>
                <input
                  type="checkbox"
                  className={styles.wfCheckbox}
                  checked={selected.has(item.candidate_id)}
                  onChange={() => {}}
                />
                <div className={styles.wfItemInfo}>
                  <div className={styles.wfItemName}>
                    {item.task_summary || '未命名技能'}
                  </div>
                  <div className={styles.wfItemDesc}>
                    候选ID: {item.candidate_id}
                    {item.source_portal_id ? ` · 来源 Portal: ${item.source_portal_id}` : ''}
                  </div>
                  <div className={styles.wfItemDesc}>
                    状态: {item.status}/{item.rollout_status} · 建议: {item.recommendation}
                  </div>
                </div>
                <div className={styles.wfItemMeta}>
                  分数 {(item.score * 100).toFixed(1)}
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && items.length > 0 && (
          <>
            <div className={styles.sectionDivider}>生成绑定草案（只读，不执行）</div>
            <div className={styles.formGroup}>
              <label className={styles.label}>目标 Agent ID（可选）</label>
              <input
                className={styles.input}
                placeholder="例如：agent_xxx（留空会生成待填写占位）"
                value={targetAgentId}
                onChange={(e) => setTargetAgentId(e.target.value)}
              />
            </div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <button
                className={`${styles.btn} ${styles.btnSecondary}`}
                disabled={selectedItems.length === 0}
                onClick={() => setShowDraft(true)}
              >
                生成草案（{selectedItems.length}）
              </button>
              <button
                className={`${styles.btn} ${styles.btnSecondary}`}
                disabled={selectedItems.length === 0}
                onClick={copyDraft}
              >
                {copyStatus === 'copied' ? '已复制' : copyStatus === 'failed' ? '复制失败' : '一键复制'}
              </button>
              <button
                className={`${styles.btn} ${styles.btnGhost}`}
                onClick={() => {
                  setShowDraft(false);
                  setSelectedIds([]);
                  setCopyStatus('idle');
                }}
              >
                清空选择
              </button>
            </div>
            {showDraft && (
              <div className={styles.formGroup} style={{ background: 'rgba(15,23,42,0.5)', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontSize: '0.78rem', marginBottom: 8, opacity: 0.85 }}>
                  待确认操作（复制给运维/管理员执行）
                </div>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: '0.72rem', lineHeight: 1.5 }}>
{draftText}
                </pre>
              </div>
            )}
          </>
        )}

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
  const [transferTarget, setTransferTarget] = useState<Portal | null>(null);
  const [transferLoading, setTransferLoading] = useState(false);
  const [transferItems, setTransferItems] = useState<ArtifactTransferRecommendation[]>([]);

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
      child_portal_ids: form.child_portal_ids,
      auto_discover_child_portals: form.auto_discover_child_portals,
      disabled_child_portal_ids: form.disabled_child_portal_ids,
      provider: form.provider,
      model: form.model,
      api_key: form.api_key || undefined,
      base_url: form.base_url || undefined,
      memory_enabled: form.memory_enabled,
      global_memory_enabled: form.global_memory_enabled,
      memory_provider: form.memory_provider,
      mempalace_palace_path: form.mempalace_palace_path || undefined,
      mempalace_wing_strategy: form.mempalace_wing_strategy || undefined,
      mempalace_default_room: form.mempalace_default_room || undefined,
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
    const cachePrefix = `proton.portal.session.${portal.id}.`;
    for (let i = localStorage.length - 1; i >= 0; i -= 1) {
      const key = localStorage.key(i);
      if (key && key.startsWith(cachePrefix)) {
        localStorage.removeItem(key);
      }
    }
    await loadAll();
  };

  const handleOpenTransferRecommendations = async (portal: Portal) => {
    setTransferTarget(portal);
    setTransferItems([]);
    setTransferLoading(true);
    try {
      const payload = await api.getArtifactTransferRecommendations({
        target_portal_id: portal.id,
        top_k: 10,
        min_score: 0.15,
        include_pending: true,
      });
      setTransferItems(payload.items || []);
    } catch (e) {
      console.error(e);
      setTransferItems([]);
    } finally {
      setTransferLoading(false);
    }
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
                    title="迁移建议"
                    onClick={() => handleOpenTransferRecommendations(portal)}
                  >
                    🔄
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
          portals={portals}
          workflows={workflows}
          onClose={() => setCreateOpen(false)}
          onSave={handleSave}
        />
      )}

      {/* Edit modal */}
      {editTarget && (
        <PortalModal
          portal={editTarget}
          portals={portals}
          workflows={workflows}
          onClose={() => setEditTarget(null)}
          onSave={handleSave}
        />
      )}

      {/* Key modal */}
      {keyTarget && (
        <KeyModal portal={keyTarget} onClose={() => setKeyTarget(null)} />
      )}

      {transferTarget && (
        <TransferRecommendationModal
          portal={transferTarget}
          loading={transferLoading}
          items={transferItems}
          onClose={() => {
            setTransferTarget(null);
            setTransferItems([]);
          }}
        />
      )}
    </div>
  );
};

export default PortalList;
