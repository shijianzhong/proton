import React, { useCallback, useEffect, useRef, useState } from 'react';
import styles from './PortalChat.module.css';
import { Portal } from './PortalList';
import { api } from '../api/client';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const SESSION_CACHE_PREFIX = 'proton.portal.session.';
const SESSION_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_NODE_STREAM_CARDS = 40;
const NODE_THINKING_FLUSH_MS = 80;
const MAX_TIMELINE_ITEMS = 120;

/* ------------------------------------------------------------------ */
/*  Types                                                               */
/* ------------------------------------------------------------------ */

interface PortalChatProps {
  portal: Portal;
  onBack: () => void;
  hideBackButton?: boolean;
}

type MsgRole = 'user' | 'assistant' | 'event';

interface ChatMsg {
  id: string;
  role: MsgRole;
  content: string;
  eventType?: string;
  meta?: any;
}

interface TimelineItem {
  id: string;
  label: string;
  status: 'running' | 'done' | 'error';
  detail?: string;
  updatedAt: number;
}

type ChannelName = 'telegram' | 'dingtalk' | 'weixin' | 'feishu';

/* ------------------------------------------------------------------ */
/*  SSE helper                                                          */
/* ------------------------------------------------------------------ */

function portalChat(
  portalId: string,
  sessionId: string,
  message: string,
  userId: string,
  onEvent: (e: any) => void,
  onDone: () => void,
  onError: (e: Error) => void
): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/portals/${portalId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message, user_id: userId, stream: true }),
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';
        for (const line of lines) {
          const t = line.trim();
          if (!t.startsWith('data: ')) continue;
          const raw = t.slice(6);
          if (raw === '[DONE]') { onDone(); return; }
          try { onEvent(JSON.parse(raw)); } catch {}
        }
      }
      onDone();
    } catch (e: any) {
      if (e.name === 'AbortError') return;
      onError(e);
    }
  })();
  return () => ctrl.abort();
}

async function createSession(portalId: string, userId: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/portals/${portalId}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
  });
  const data = await res.json();
  return data.session_id;
}

async function getSession(portalId: string, sessionId: string): Promise<any | null> {
  const res = await fetch(`${BASE_URL}/api/portals/${portalId}/sessions/${sessionId}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`获取会话失败: ${res.status}`);
  return await res.json();
}

function sweepExpiredSessionCache(now = Date.now()) {
  for (let i = localStorage.length - 1; i >= 0; i -= 1) {
    const key = localStorage.key(i);
    if (!key || !key.startsWith(SESSION_CACHE_PREFIX)) continue;
    const raw = localStorage.getItem(key);
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw);
      if (parsed?.savedAt && now - Number(parsed.savedAt) > SESSION_CACHE_TTL_MS) {
        localStorage.removeItem(key);
      }
    } catch {
      // Keep backward compatibility with old plain-string session_id format.
    }
  }
}

function readCachedSessionId(cacheKey: string, now = Date.now()): string | null {
  const raw = localStorage.getItem(cacheKey);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    const sid = String(parsed?.sessionId || '');
    const savedAt = Number(parsed?.savedAt || 0);
    if (!sid || !savedAt || now - savedAt > SESSION_CACHE_TTL_MS) {
      localStorage.removeItem(cacheKey);
      return null;
    }
    return sid;
  } catch {
    // Backward compatibility for legacy plain session id value.
    return raw;
  }
}

function writeCachedSessionId(cacheKey: string, sessionId: string, now = Date.now()) {
  localStorage.setItem(cacheKey, JSON.stringify({ sessionId, savedAt: now }));
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                      */
/* ------------------------------------------------------------------ */

const EventCard: React.FC<{ msg: ChatMsg }> = ({ msg }) => {
  const { eventType, meta } = msg;

  if (eventType === 'intent_understood' && meta?.intent) {
    const intent = meta.intent;
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>🎯</span> 意图理解
        </div>
        <div style={{ marginBottom: 6 }}>{intent.understood_intent}</div>
        {intent.dispatch_plans?.length > 0 && (
          <div>
            <div style={{ marginBottom: 4, fontSize: '0.72rem' }}>将调用：</div>
            {intent.dispatch_plans.map((p: any, i: number) => (
              <span key={i} className={styles.eventChip}>
                ⚡ {p.workflow_name}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (eventType === 'workflow_dispatch_start') {
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>▶</span>
          <span className={`${styles.eventChip} ${styles.eventChipBlue}`}>
            {meta?.workflow_name ?? '工作流'}
          </span>
          执行中…
        </div>
      </div>
    );
  }

  if (eventType === 'portal_dispatch_start') {
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>🧭</span>
          <span className={`${styles.eventChip} ${styles.eventChipBlue}`}>
            {meta?.workflow_name ?? '子 Portal'}
          </span>
          调用中…
        </div>
      </div>
    );
  }

  if (eventType === 'portal_dispatch_result') {
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>✅</span>
          <span className={styles.eventChip}>{meta?.workflow_name ?? '子 Portal'}</span>
          返回结果
        </div>
      </div>
    );
  }

  if (eventType === 'memory_behavior_suggestion') {
    const suggestions = Array.isArray(meta?.suggestions) ? meta.suggestions : [];
    const first = suggestions[0];
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>🧠</span> 记忆行为建议
        </div>
        {first ? (
          <div style={{ marginTop: 4, fontSize: '0.78rem', opacity: 0.9 }}>
            {String(first.title || '建议')} · {String(first.detail || '')}
          </div>
        ) : (
          <div style={{ marginTop: 4, fontSize: '0.78rem', opacity: 0.9 }}>
            已生成建议，可用于调整回复策略。
          </div>
        )}
      </div>
    );
  }

  if (eventType === 'auto_skill_created') {
    const candidateId = String(meta?.candidate_id || '');
    const score = meta?.assessment?.score;
    const successRate = meta?.assessment?.signals?.success_rate;
    const rollout = String(meta?.rollout_status || 'grayscale');
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>🤖</span> 自动创建了新 Skill（受控灰度）
        </div>
        <div style={{ marginTop: 4, fontSize: '0.78rem', opacity: 0.9 }}>
          候选ID: {candidateId || 'unknown'}
        </div>
        <div style={{ marginTop: 4, fontSize: '0.78rem', opacity: 0.9 }}>
          评估分: {typeof score === 'number' ? score.toFixed(2) : 'N/A'} · 成功率: {typeof successRate === 'number' ? `${(successRate * 100).toFixed(1)}%` : 'N/A'} · 状态: {rollout}
        </div>
      </div>
    );
  }

  if (eventType === 'auto_skill_revised') {
    const candidateId = String(meta?.candidate_id || '');
    const toolName = String(meta?.tool_name || 'unknown_tool');
    const errorType = String(meta?.error_type || 'unknown');
    const rollout = String(meta?.rollout_status || 'pending');
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>🛠️</span> 自动修订了 Skill（错误驱动）
        </div>
        <div style={{ marginTop: 4, fontSize: '0.78rem', opacity: 0.9 }}>
          工具: {toolName} · 错误类型: {errorType}
        </div>
        <div style={{ marginTop: 4, fontSize: '0.78rem', opacity: 0.9 }}>
          候选ID: {candidateId || 'unknown'} · 发布状态: {rollout}
        </div>
      </div>
    );
  }

  if (eventType === 'workflow_dispatch_result') {
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}>
          <span>✅</span>
          <span className={styles.eventChip}>{meta?.workflow_name}</span>
          完成
        </div>
        {meta?.workflow_result && (
          <div style={{ marginTop: 4, whiteSpace: 'pre-wrap', fontSize: '0.76rem', opacity: 0.8 }}>
            {meta.workflow_result.slice(0, 300)}{meta.workflow_result.length > 300 ? '…' : ''}
          </div>
        )}
      </div>
    );
  }

  if (eventType === 'synthesis_start') {
    return (
      <div className={styles.eventCard}>
        <div className={styles.eventTitle}><span>✍️</span> 正在整合回答…</div>
      </div>
    );
  }

  if (eventType === 'node_stream') {
    const status = meta?.status || 'running';
    const title = meta?.title || '节点执行';
    const detail = meta?.detail || '';
    const text = meta?.text || '';
    const duration = meta?.durationMs ? `${Math.round(meta.durationMs)}ms` : '';
    const statusEmoji = status === 'done' ? '✅' : status === 'error' ? '❌' : '⚡';
    const summary = `${statusEmoji} ${title}${duration ? ` · ${duration}` : ''}${detail ? ` · ${detail}` : ''}`;
    const openByDefault = status !== 'done';
    return (
      <div className={styles.eventCard}>
        <details open={openByDefault} className={styles.nodeDetails}>
          <summary className={styles.nodeSummary}>{summary}</summary>
          <div className={styles.nodeBody}>
            {text ? text : '（等待输出…）'}
          </div>
        </details>
      </div>
    );
  }

  return null;
};

/* ------------------------------------------------------------------ */
/*  Main Component                                                      */
/* ------------------------------------------------------------------ */

const PortalChat: React.FC<PortalChatProps> = ({ portal, onBack, hideBackButton }) => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [channelOpen, setChannelOpen] = useState(false);

  const userId = 'default';
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const assistantIdRef = useRef<string | null>(null);
  const synthesisEventIdRef = useRef<string | null>(null);
  const nodeCardIdRef = useRef<Record<string, string>>({});
  const nodePendingRef = useRef<Record<string, string>>({});
  const nodeFlushTimerRef = useRef<number | null>(null);
  const sessionStorageKey = `proton.portal.session.${portal.id}.${userId}`;

  // Init session
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        sweepExpiredSessionCache();
        const cachedSessionId = readCachedSessionId(sessionStorageKey);
        if (cachedSessionId) {
          const session = await getSession(portal.id, cachedSessionId);
          if (session && !cancelled) {
            setSessionId(cachedSessionId);
            const restored: ChatMsg[] = (session.messages || [])
              .filter((m: any) => m?.role === 'user' || m?.role === 'assistant')
              .map((m: any) => ({
                id: Math.random().toString(36).slice(2),
                role: m.role,
                content: String(m.content || ''),
              }));
            setMessages(restored);
            return;
          }
          localStorage.removeItem(sessionStorageKey);
        }

        const sid = await createSession(portal.id, userId);
        if (!cancelled) {
          writeCachedSessionId(sessionStorageKey, sid);
          setSessionId(sid);
          setMessages([]);
        }
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      if (nodeFlushTimerRef.current) {
        window.clearTimeout(nodeFlushTimerRef.current);
        nodeFlushTimerRef.current = null;
      }
      abortRef.current?.();
    };
  }, [portal.id, sessionStorageKey, userId]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const uid = () => Math.random().toString(36).slice(2);

  const flushPendingNodeText = useCallback(() => {
    const pending = nodePendingRef.current;
    nodePendingRef.current = {};
    nodeFlushTimerRef.current = null;
    const ids = Object.keys(pending);
    if (ids.length === 0) return;
    setMessages(prev => prev.map(m => {
      const delta = pending[m.id];
      if (!delta) return m;
      return {
        ...m,
        meta: {
          ...(m.meta || {}),
          status: 'running',
          text: `${m.meta?.text || ''}${delta}`,
        },
      };
    }));
  }, []);

  const queueNodeTextDelta = useCallback((cardId: string, delta: string) => {
    nodePendingRef.current[cardId] = `${nodePendingRef.current[cardId] || ''}${delta}`;
    if (nodeFlushTimerRef.current === null) {
      nodeFlushTimerRef.current = window.setTimeout(flushPendingNodeText, NODE_THINKING_FLUSH_MS);
    }
  }, [flushPendingNodeText]);

  const upsertTimeline = (
    id: string,
    patch: Omit<TimelineItem, 'id' | 'updatedAt'> & Partial<Pick<TimelineItem, 'detail'>>
  ) => {
    setTimeline(prev => {
      const now = Date.now();
      const idx = prev.findIndex(x => x.id === id);
      let next: TimelineItem[];
      if (idx < 0) {
        next = [...prev, { id, updatedAt: now, ...patch }];
      } else {
        next = [...prev];
        next[idx] = { ...next[idx], ...patch, updatedAt: now };
      }
      if (next.length > MAX_TIMELINE_ITEMS) {
        next = next.slice(next.length - MAX_TIMELINE_ITEMS);
      }
      return next;
    });
  };

  const appendMsg = (msg: Omit<ChatMsg, 'id'>) =>
    setMessages(prev => [...prev, { ...msg, id: uid() }]);

  const updateLastAssistant = (delta: string) => {
    if (!assistantIdRef.current) return;
    const targetId = assistantIdRef.current;
    setMessages(prev => {
      const next = [...prev];
      const idx = next.findIndex(m => m.id === targetId);
      if (idx < 0) return prev;
      const updated = { ...next[idx], content: (next[idx].content || '') + delta };
      // Keep synthesized output at the bottom of chat.
      next.splice(idx, 1);
      next.push(updated);
      return next;
    });
  };

  const updateEventMsgById = (id: string, updater: (m: ChatMsg) => ChatMsg) => {
    setMessages(prev => prev.map(m => (m.id === id ? updater(m) : m)));
  };

  const send = () => {
    if (!input.trim() || loading || !sessionId) return;
    const text = input.trim();
    setInput('');
    setLoading(true);
    setTimeline([]);
    nodeCardIdRef.current = {};
    synthesisEventIdRef.current = null;

    appendMsg({ role: 'user', content: text });

    // placeholder for assistant
    const aId = uid();
    assistantIdRef.current = aId;
    setMessages(prev => [...prev, { id: aId, role: 'assistant', content: '' }]);

    abortRef.current = portalChat(
      portal.id,
      sessionId,
      text,
      userId,
      (event) => {
        const type = event.type;

        if (type === 'intent_understood') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
          const plans = event.intent?.dispatch_plans ?? [];
          upsertTimeline(`intent:${event.session_id}`, {
            label: '意图理解',
            status: 'done',
            detail: plans.length > 0 ? `命中 ${plans.length} 个候选` : '未命中明确候选',
          });
        } else if (type === 'portal_dispatch_start') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
          upsertTimeline(`portal:${event.workflow_id}`, {
            label: `子Portal: ${event.workflow_name || event.workflow_id}`,
            status: 'running',
            detail: '执行中',
          });
        } else if (type === 'portal_dispatch_result') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
          upsertTimeline(`portal:${event.workflow_id}`, {
            label: `子Portal: ${event.workflow_name || event.workflow_id}`,
            status: 'done',
            detail: '执行完成',
          });
        } else if (type === 'workflow_dispatch_start') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
          upsertTimeline(`wf:${event.workflow_id}`, {
            label: `工作流: ${event.workflow_name || event.workflow_id}`,
            status: 'running',
            detail: '执行中',
          });
        } else if (type === 'workflow_dispatch_result') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
          upsertTimeline(`wf:${event.workflow_id}`, {
            label: `工作流: ${event.workflow_name || event.workflow_id}`,
            status: 'done',
            detail: '执行完成',
          });
        } else if (type === 'auto_skill_created') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event.metadata || event });
          const candidateId = String(event.metadata?.candidate_id || 'unknown');
          const score = event.metadata?.assessment?.score;
          upsertTimeline(`auto-skill:${candidateId}`, {
            label: `自动创建Skill: ${candidateId}`,
            status: 'done',
            detail: typeof score === 'number' ? `评估分 ${score.toFixed(2)}（灰度）` : '灰度发布',
          });
        } else if (type === 'auto_skill_revised') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event.metadata || event });
          const candidateId = String(event.metadata?.candidate_id || 'unknown');
          const toolName = String(event.metadata?.tool_name || 'unknown_tool');
          const rollout = String(event.metadata?.rollout_status || 'pending');
          upsertTimeline(`auto-revision:${candidateId}`, {
            label: `自动修订Skill: ${toolName}`,
            status: rollout === 'grayscale' ? 'done' : 'running',
            detail: `候选 ${candidateId} · ${rollout}`,
          });
        } else if (type === 'memory_behavior_suggestion') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event.metadata || event });
          const count = Array.isArray(event.metadata?.suggestions)
            ? event.metadata.suggestions.length
            : 0;
          upsertTimeline(`memory-suggest:${Date.now()}`, {
            label: '记忆行为建议',
            status: 'done',
            detail: count > 0 ? `生成 ${count} 条建议` : '已生成建议',
          });
        } else if (type === 'workflow_execution_event') {
          const meta = event.metadata || {};
          const childType = String(meta.child_event_type || '').toLowerCase();
          if (childType === 'intent_understood') {
            const plans = meta.child_event?.intent?.dispatch_plans || [];
            upsertTimeline(`child-intent:${meta.child_portal_id}`, {
              label: `子Portal意图: ${meta.child_portal_name || meta.child_portal_id}`,
              status: 'done',
              detail: plans.length > 0 ? `命中 ${plans.length} 个 workflow` : '未命中 workflow',
            });
            return;
          }
          if (childType === 'workflow_dispatch_start') {
            upsertTimeline(`child-wf:${meta.child_portal_id}:${meta.child_event?.workflow_id}`, {
              label: `子Portal工作流: ${meta.child_event?.workflow_name || meta.child_event?.workflow_id}`,
              status: 'running',
              detail: '执行中',
            });
            return;
          }
          if (childType === 'workflow_dispatch_result') {
            upsertTimeline(`child-wf:${meta.child_portal_id}:${meta.child_event?.workflow_id}`, {
              label: `子Portal工作流: ${meta.child_event?.workflow_name || meta.child_event?.workflow_id}`,
              status: 'done',
              detail: '执行完成',
            });
            return;
          }
          if (childType === 'synthesis_start') {
            upsertTimeline(`child-syn:${meta.child_portal_id}`, {
              label: `子Portal综合: ${meta.child_portal_name || meta.child_portal_id}`,
              status: 'running',
              detail: '生成中',
            });
            return;
          }

          const ex = meta.execution_event || meta.child_event?.metadata?.execution_event || {};
          const exType = String(ex.event_type || '').toLowerCase();
          const childPrefix = meta.child_portal_id ? `child:${meta.child_portal_id}:` : '';
          const nodeKey = `${childPrefix}${event.workflow_id}:${ex.node_id || ex.node_name || 'unknown'}`;
          const nodeTitlePrefix = meta.child_portal_name
            ? `子Portal ${meta.child_portal_name} / `
            : '';
          const nodeTitle = `${nodeTitlePrefix}${ex.node_name || ex.node_id || 'unknown'}`;
          if (exType === 'node_start') {
            const cardId = uid();
            nodeCardIdRef.current[nodeKey] = cardId;
            setMessages(prev => {
              const eventIds = prev.filter(m => m.eventType === 'node_stream').map(m => m.id);
              const removeCount = Math.max(0, eventIds.length + 1 - MAX_NODE_STREAM_CARDS);
              const toRemove = new Set(eventIds.slice(0, removeCount));
              const kept = removeCount > 0 ? prev.filter(m => !toRemove.has(m.id)) : prev;
              return [
                ...kept,
                {
                  id: cardId,
                  role: 'event',
                  content: '',
                  eventType: 'node_stream',
                  meta: {
                    status: 'running',
                    title: nodeTitle,
                    detail: '开始执行',
                    text: '',
                  },
                },
              ];
            });
            upsertTimeline(`${childPrefix}node:${event.workflow_id}:${ex.node_id || ex.node_name}`, {
              label: `节点: ${ex.node_name || ex.node_id || 'unknown'}`,
              status: 'running',
              detail: '开始执行',
            });
          } else if (exType === 'node_thinking') {
            const cardId = nodeCardIdRef.current[nodeKey];
            if (cardId && ex.delta_content) {
              queueNodeTextDelta(cardId, String(ex.delta_content));
            }
          } else if (exType === 'node_complete') {
            flushPendingNodeText();
            const duration = ex.duration_ms ? `${Math.round(ex.duration_ms)}ms` : '完成';
            const cardId = nodeCardIdRef.current[nodeKey];
            if (cardId) {
              updateEventMsgById(cardId, (m) => ({
                ...m,
                meta: {
                  ...(m.meta || {}),
                  status: 'done',
                  title: m.meta?.title || nodeTitle,
                  detail: duration,
                  durationMs: ex.duration_ms,
                  text: m.meta?.text || ex.content || '',
                },
              }));
            }
            upsertTimeline(`${childPrefix}node:${event.workflow_id}:${ex.node_id || ex.node_name}`, {
              label: `节点: ${ex.node_name || ex.node_id || 'unknown'}`,
              status: 'done',
              detail: duration,
            });
          } else if (exType === 'node_error' || exType === 'workflow_error') {
            flushPendingNodeText();
            const cardId = nodeCardIdRef.current[nodeKey];
            if (cardId) {
              updateEventMsgById(cardId, (m) => ({
                ...m,
                meta: {
                  ...(m.meta || {}),
                  status: 'error',
                  title: m.meta?.title || nodeTitle,
                  detail: ex.error || '执行错误',
                },
              }));
            }
            upsertTimeline(`${childPrefix}node:${event.workflow_id}:${ex.node_id || ex.node_name || exType}`, {
              label: `节点: ${ex.node_name || ex.node_id || 'unknown'}`,
              status: 'error',
              detail: ex.error || '执行错误',
            });
          } else if (exType === 'workflow_start') {
            upsertTimeline(`${childPrefix}wfstream:${event.workflow_id}`, {
              label: `工作流轨迹: ${event.workflow_name || event.workflow_id}`,
              status: 'running',
              detail: '开始',
            });
          } else if (exType === 'workflow_complete') {
            const duration = ex.duration_ms ? `${Math.round(ex.duration_ms)}ms` : '完成';
            upsertTimeline(`${childPrefix}wfstream:${event.workflow_id}`, {
              label: `工作流轨迹: ${event.workflow_name || event.workflow_id}`,
              status: 'done',
              detail: duration,
            });
          }
        } else if (type === 'synthesis_start') {
          const eid = uid();
          synthesisEventIdRef.current = eid;
          setMessages(prev => [...prev, { id: eid, role: 'event', content: '', eventType: type, meta: event }]);
          upsertTimeline(`synthesis:${event.session_id}`, {
            label: '结果综合',
            status: 'running',
            detail: '生成中',
          });
        } else if (type === 'content' && event.delta) {
          if (synthesisEventIdRef.current) {
            const sid = synthesisEventIdRef.current;
            setMessages(prev => prev.filter(m => m.id !== sid));
            synthesisEventIdRef.current = null;
          }
          updateLastAssistant(event.delta);
        } else if (type === 'error') {
          updateLastAssistant(`\n\n❌ 错误：${event.error}`);
          upsertTimeline(`error:${event.session_id}`, {
            label: '执行错误',
            status: 'error',
            detail: event.error || 'unknown',
          });
        }
      },
      () => {
        setLoading(false);
        if (synthesisEventIdRef.current) {
          const sid = synthesisEventIdRef.current;
          setMessages(prev => prev.filter(m => m.id !== sid));
          synthesisEventIdRef.current = null;
        }
        assistantIdRef.current = null;
      },
      (err) => {
        updateLastAssistant(`\n\n❌ 请求失败：${err.message}`);
        setLoading(false);
        if (synthesisEventIdRef.current) {
          const sid = synthesisEventIdRef.current;
          setMessages(prev => prev.filter(m => m.id !== sid));
          synthesisEventIdRef.current = null;
        }
        assistantIdRef.current = null;
      }
    );
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const suggestions = [
    '你好，你能做什么？',
    '给我介绍一下你的能力',
    '帮我查一下最近的信息',
  ];

  return (
    <div className={styles.container}>
      {/* Top bar */}
      <div className={styles.topbar}>
        {!hideBackButton && <button className={styles.backBtn} onClick={onBack}>← 返回</button>}
        <div className={styles.topbarInfo}>
          <div className={styles.topbarTitle}>🧠 {portal.name}</div>
          <div className={styles.topbarMeta}>
            {portal.workflow_ids.length} 个工作流 · {portal.provider} / {portal.model}
          </div>
        </div>
        <button
          className={styles.backBtn}
          style={{ marginLeft: 10 }}
          onClick={() => setChannelOpen(true)}
        >
          🔌 渠道接入
        </button>
        {portal.memory_enabled && (
          <span className={`${styles.badge} ${styles.badgeGreen}`}>记忆开启</span>
        )}
        {!sessionId && <span className={`${styles.badge} ${styles.badgeBlue}`}>连接中…</span>}
      </div>

      {/* Body */}
      <div className={styles.body}>
        {/* Messages */}
        <div className={styles.messages}>
          {messages.length === 0 ? (
            <div className={styles.welcome}>
              <div className={styles.welcomeIcon}>🧠</div>
              <h3>{portal.name}</h3>
              <p>
                {portal.description || '这是一个超级入口，能理解你的需求并自动调用合适的工作流来帮助你。'}
              </p>
              <div className={styles.welcomeChips}>
                {suggestions.map(s => (
                  <div key={s} className={styles.welcomeChip} onClick={() => { setInput(s); }}>
                    {s}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map(msg => {
                if (msg.role === 'event') {
                  return <EventCard key={msg.id} msg={msg} />;
                }
                if (msg.role === 'user') {
                  return (
                    <div key={msg.id} className={`${styles.msgRow} ${styles.msgRowUser}`}>
                      <div className={`${styles.avatar} ${styles.avatarUser}`}>👤</div>
                      <div className={`${styles.bubble} ${styles.bubbleUser}`}>{msg.content}</div>
                    </div>
                  );
                }
                // assistant
                return (
                  <div key={msg.id} className={styles.msgRow}>
                    <div className={`${styles.avatar} ${styles.avatarAssistant}`}>🧠</div>
                    <div className={`${styles.bubble} ${styles.bubbleAssistant}`}>
                      {msg.content || (loading && assistantIdRef.current === msg.id ? (
                        <div className={styles.thinking}>
                          <div className={styles.dot} />
                          <div className={styles.dot} />
                          <div className={styles.dot} />
                        </div>
                      ) : '…')}
                    </div>
                  </div>
                );
              })}
            </>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Side panel: bound workflows */}
        <div className={styles.sidePanel}>
          <div className={styles.sidePanelHeader}>执行时间线</div>
          <div className={styles.sidePanelBody}>
            {timeline.length === 0 ? (
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', textAlign: 'center', marginTop: 20 }}>
                等待执行事件…
              </div>
            ) : (
              [...timeline]
                .sort((a, b) => a.updatedAt - b.updatedAt)
                .map(item => (
                <div
                  key={item.id}
                  className={`${styles.wfChip} ${item.status === 'running' ? styles.wfChipActive : ''}`}
                >
                  <div className={styles.timelineTitle}>
                    <span>
                      {item.status === 'running' ? '⚡' : item.status === 'done' ? '✅' : '❌'} {item.label}
                    </span>
                  </div>
                  {item.detail && <div className={styles.timelineDetail}>{item.detail}</div>}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Input */}
      <div className={styles.inputArea}>
        <div className={styles.inputRow}>
          <textarea
            className={styles.textarea}
            placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            disabled={loading || !sessionId}
            rows={1}
          />
          <button
            className={styles.sendBtn}
            onClick={send}
            disabled={loading || !input.trim() || !sessionId}
            title="发送"
          >
            ↑
          </button>
        </div>
        <div className={styles.inputHint}>
          由 {portal.provider}/{portal.model} 驱动 · 绑定 {portal.workflow_ids.length} 个工作流
        </div>
      </div>

      {channelOpen && (
        <ChannelModal portalId={portal.id} onClose={() => setChannelOpen(false)} />
      )}
    </div>
  );
};

export default PortalChat;

const ChannelModal: React.FC<{ portalId: string; onClose: () => void }> = ({ portalId, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [channels, setChannels] = useState<Record<string, any>>({});
  const [editing, setEditing] = useState<ChannelName | null>(null);

  const [telegramToken, setTelegramToken] = useState('');
  const [dingtalkClientId, setDingtalkClientId] = useState('');
  const [dingtalkClientSecret, setDingtalkClientSecret] = useState('');
  const [feishuAppId, setFeishuAppId] = useState('');
  const [feishuAppSecret, setFeishuAppSecret] = useState('');
  const [feishuMode, setFeishuMode] = useState<'ws' | 'webhook'>('ws');
  const [feishuDomain, setFeishuDomain] = useState('https://open.feishu.cn');
  const [feishuVerificationToken, setFeishuVerificationToken] = useState('');
  const [feishuEncryptKey, setFeishuEncryptKey] = useState('');

  const [weixinLoginId, setWeixinLoginId] = useState<string | null>(null);
  const [weixinQrUrl, setWeixinQrUrl] = useState<string | null>(null);
  const [weixinStatus, setWeixinStatus] = useState<string>('');
  const [pairing, setPairing] = useState<Record<string, any>>({});

  const refresh = async () => {
    setLoading(true);
    try {
      const data = await (api as any).getPortalChannels(portalId);
      setChannels(data || {});
      const nextPairing: Record<string, any> = {};
      for (const ch of ['weixin', 'feishu'] as ChannelName[]) {
        try {
          nextPairing[ch] = await (api as any).getPortalChannelAllowlist(portalId, ch);
        } catch {}
      }
      setPairing(nextPairing);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [portalId]);

  useEffect(() => {
    if (!weixinLoginId) return;
    let stopped = false;
    const tick = async () => {
      try {
        const data = await (api as any).pollWeixinQrLogin(portalId, weixinLoginId);
        if (stopped) return;
        setWeixinStatus(data?.status || '');
        if (data?.status === 'confirmed') {
          await refresh();
          setWeixinLoginId(null);
          return;
        }
      } catch {}
      if (!stopped) setTimeout(tick, 1200);
    };
    tick();
    return () => { stopped = true; };
  }, [weixinLoginId, portalId]);

  const statusLine = (c: any) => {
    if (!c) return '未配置';
    if (!c.enabled) return '已禁用';
    if (c.connected) return '🟢 已连接';
    if (c.last_error) return `🔴 ${c.last_error}`;
    if (c.meta?.running) return '🟠 连接中…';
    return '🟠 未连接';
  };

  const saveTelegram = async () => {
    await (api as any).upsertPortalChannel(portalId, 'telegram', {
      enabled: true,
      config: { token: telegramToken },
    });
    setEditing(null);
    await refresh();
  };

  const saveDingTalk = async () => {
    await (api as any).upsertPortalChannel(portalId, 'dingtalk', {
      enabled: true,
      config: { client_id: dingtalkClientId, client_secret: dingtalkClientSecret },
    });
    setEditing(null);
    await refresh();
  };

  const saveFeishu = async () => {
    await (api as any).upsertPortalChannel(portalId, 'feishu', {
      enabled: true,
      config: {
        app_id: feishuAppId,
        app_secret: feishuAppSecret,
        mode: feishuMode,
        domain: feishuDomain,
        verification_token: feishuVerificationToken,
        encrypt_key: feishuEncryptKey,
      },
    });
    setEditing(null);
    await refresh();
  };

  const startWeixin = async () => {
    const data = await (api as any).startWeixinQrLogin(portalId);
    setWeixinLoginId(data?.login_id);
    setWeixinQrUrl(data?.qrcode_img_content || null);
    setWeixinStatus(data?.status || 'wait');
  };

  const createPairing = async (channel: ChannelName) => {
    const data = await (api as any).createPortalChannelPairingCode(portalId, channel, { ttl_seconds: 900 });
    setPairing(prev => ({ ...prev, [channel]: { ...(prev[channel] || {}), ...data } }));
  };

  const unbind = async (channel: ChannelName) => {
    await (api as any).deletePortalChannel(portalId, channel);
    await refresh();
  };

  const row = (channel: ChannelName, title: string, extra?: React.ReactNode) => (
    <div style={{ border: '1px solid var(--color-secondary)', borderRadius: 10, padding: 12, marginTop: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div>
          <div style={{ fontWeight: 700 }}>{title}</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
            {statusLine(channels[channel])}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={styles.backBtn} onClick={() => setEditing(channel)}>配置</button>
          <button className={styles.backBtn} onClick={() => unbind(channel)}>解绑</button>
        </div>
      </div>
      {extra}
    </div>
  );

  const editPanel = () => {
    if (!editing) return null;
    const panelStyle: React.CSSProperties = { marginTop: 10, padding: 12, borderRadius: 10, border: '1px solid var(--color-secondary)' };

    if (editing === 'telegram') {
      return (
        <div style={panelStyle}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Telegram Token</div>
          <input
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)' }}
            placeholder="123456:ABC..."
            value={telegramToken}
            onChange={e => setTelegramToken(e.target.value)}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className={styles.backBtn} onClick={saveTelegram}>保存并连接</button>
            <button className={styles.backBtn} onClick={() => setEditing(null)}>取消</button>
          </div>
        </div>
      );
    }

    if (editing === 'dingtalk') {
      return (
        <div style={panelStyle}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>钉钉 Stream 凭证</div>
          <input
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)' }}
            placeholder="Client ID"
            value={dingtalkClientId}
            onChange={e => setDingtalkClientId(e.target.value)}
          />
          <input
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)', marginTop: 8 }}
            placeholder="Client Secret"
            value={dingtalkClientSecret}
            onChange={e => setDingtalkClientSecret(e.target.value)}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className={styles.backBtn} onClick={saveDingTalk}>保存并连接</button>
            <button className={styles.backBtn} onClick={() => setEditing(null)}>取消</button>
          </div>
        </div>
      );
    }

    if (editing === 'feishu') {
      return (
        <div style={panelStyle}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>飞书 App 凭证</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className={styles.backBtn} onClick={() => setFeishuMode('ws')} disabled={feishuMode === 'ws'}>WebSocket</button>
            <button className={styles.backBtn} onClick={() => setFeishuMode('webhook')} disabled={feishuMode === 'webhook'}>Webhook</button>
          </div>
          <input
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)', marginTop: 8 }}
            placeholder="Domain (默认 https://open.feishu.cn)"
            value={feishuDomain}
            onChange={e => setFeishuDomain(e.target.value)}
          />
          <input
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)', marginTop: 8 }}
            placeholder="App ID (cli_xxx)"
            value={feishuAppId}
            onChange={e => setFeishuAppId(e.target.value)}
          />
          <input
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)', marginTop: 8 }}
            placeholder="App Secret"
            value={feishuAppSecret}
            onChange={e => setFeishuAppSecret(e.target.value)}
          />
          {feishuMode === 'webhook' && (
            <>
              <input
                style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)', marginTop: 8 }}
                placeholder="Verification Token（可选）"
                value={feishuVerificationToken}
                onChange={e => setFeishuVerificationToken(e.target.value)}
              />
              <input
                style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-secondary)', marginTop: 8 }}
                placeholder="Encrypt Key（可选，用于签名校验）"
                value={feishuEncryptKey}
                onChange={e => setFeishuEncryptKey(e.target.value)}
              />
              <div style={{ marginTop: 8, fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
                Webhook URL：{`${BASE_URL}/api/portals/${portalId}/channels/feishu/webhook`}
              </div>
            </>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className={styles.backBtn} onClick={saveFeishu}>保存并连接</button>
            <button className={styles.backBtn} onClick={() => setEditing(null)}>取消</button>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(15, 23, 42, 0.35)', display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 18, zIndex: 50 }} onClick={onClose}>
      <div style={{ width: '100%', maxWidth: 720, background: 'var(--color-primary)', border: '1px solid var(--color-secondary)', borderRadius: 14, padding: 18 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: '1.1rem', fontWeight: 800 }}>🔌 渠道接入</div>
            <div style={{ marginTop: 4, fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>为该入口绑定社交软件 Bot；支持微信扫码</div>
          </div>
          <button className={styles.backBtn} onClick={refresh} disabled={loading}>刷新</button>
        </div>

        {loading ? (
          <div style={{ padding: 20 }}>加载中…</div>
        ) : (
          <>
            {row('weixin', '微信（扫码登录）', (
              <div style={{ marginTop: 10 }}>
                <button className={styles.backBtn} onClick={startWeixin} disabled={!!weixinLoginId}>开始扫码</button>
                <button className={styles.backBtn} style={{ marginLeft: 8 }} onClick={() => createPairing('weixin')}>生成配对码</button>
                {pairing.weixin?.pairing_code && (
                  <div style={{ marginTop: 8, fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
                    配对码：<span style={{ color: 'var(--color-text)' }}>{pairing.weixin.pairing_code}</span>
                  </div>
                )}
                {weixinLoginId && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>状态：{weixinStatus || 'wait'}</div>
                    {weixinQrUrl && (
                      <div style={{ marginTop: 8 }}>
                        <img src={weixinQrUrl} style={{ width: 220, height: 220, borderRadius: 10, border: '1px solid var(--color-secondary)' }} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            {row('telegram', 'Telegram（Token）')}
            {row('dingtalk', '钉钉（Stream）')}
            {row('feishu', '飞书（WebSocket）', (
              <div style={{ marginTop: 10 }}>
                <button className={styles.backBtn} onClick={() => createPairing('feishu')}>生成配对码</button>
                {pairing.feishu?.pairing_code && (
                  <div style={{ marginTop: 8, fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
                    配对码：<span style={{ color: 'var(--color-text)' }}>{pairing.feishu.pairing_code}</span>
                  </div>
                )}
              </div>
            ))}
            {editPanel()}
          </>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
          <button className={styles.backBtn} onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
};
