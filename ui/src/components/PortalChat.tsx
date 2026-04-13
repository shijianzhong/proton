import React, { useEffect, useRef, useState } from 'react';
import styles from './PortalChat.module.css';
import { Portal } from './PortalList';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
  const [activeWfs, setActiveWfs] = useState<string[]>([]);

  const userId = 'default';
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const assistantIdRef = useRef<string | null>(null);

  // Init session
  useEffect(() => {
    createSession(portal.id, userId).then(setSessionId).catch(console.error);
    return () => abortRef.current?.();
  }, [portal.id]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const uid = () => Math.random().toString(36).slice(2);

  const appendMsg = (msg: Omit<ChatMsg, 'id'>) =>
    setMessages(prev => [...prev, { ...msg, id: uid() }]);

  const updateLastAssistant = (delta: string) => {
    if (!assistantIdRef.current) return;
    const targetId = assistantIdRef.current;
    setMessages(prev =>
      prev.map(m => m.id === targetId ? { ...m, content: m.content + delta } : m)
    );
  };

  const send = () => {
    if (!input.trim() || loading || !sessionId) return;
    const text = input.trim();
    setInput('');
    setLoading(true);
    setActiveWfs([]);

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
          setActiveWfs(plans.map((p: any) => p.workflow_id));
        } else if (type === 'workflow_dispatch_start') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
        } else if (type === 'workflow_dispatch_result') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
          setActiveWfs(prev => prev.filter(id => id !== event.workflow_id));
        } else if (type === 'synthesis_start') {
          appendMsg({ role: 'event', content: '', eventType: type, meta: event });
        } else if (type === 'content' && event.delta) {
          updateLastAssistant(event.delta);
        } else if (type === 'error') {
          updateLastAssistant(`\n\n❌ 错误：${event.error}`);
        }
      },
      () => {
        setLoading(false);
        assistantIdRef.current = null;
        setActiveWfs([]);
      },
      (err) => {
        updateLastAssistant(`\n\n❌ 请求失败：${err.message}`);
        setLoading(false);
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
          <div className={styles.sidePanelHeader}>绑定的工作流</div>
          <div className={styles.sidePanelBody}>
            {portal.workflow_ids.length === 0 ? (
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', textAlign: 'center', marginTop: 20 }}>
                未绑定工作流
              </div>
            ) : (
              portal.workflow_ids.map(id => (
                <div
                  key={id}
                  className={`${styles.wfChip} ${activeWfs.includes(id) ? styles.wfChipActive : ''}`}
                >
                  {activeWfs.includes(id) ? '⚡ ' : ''}
                  <span style={{ fontSize: '0.75rem', fontFamily: 'monospace', opacity: 0.6 }}>
                    {id.slice(0, 8)}…
                  </span>
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
    </div>
  );
};

export default PortalChat;
