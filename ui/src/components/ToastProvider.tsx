import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import styles from './ToastProvider.module.css';

type ToastVariant = 'success' | 'error' | 'warning' | 'info';

type ToastItem = {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
};

type ToastInput = {
  title: string;
  description?: string;
  variant?: ToastVariant;
  durationMs?: number;
};

type ToastApi = {
  show: (input: ToastInput) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  warning: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

function randomId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return ctx;
};

const VariantBarClass: Record<ToastVariant, string> = {
  success: styles.barSuccess,
  error: styles.barError,
  warning: styles.barWarning,
  info: styles.barInfo,
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timersRef = useRef<Record<string, number>>({});

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
    const t = timersRef.current[id];
    if (t) {
      window.clearTimeout(t);
      delete timersRef.current[id];
    }
  }, []);

  const show = useCallback((input: ToastInput) => {
    const id = randomId();
    const item: ToastItem = {
      id,
      title: input.title,
      description: input.description,
      variant: input.variant ?? 'info',
    };

    setItems((prev) => [item, ...prev].slice(0, 5));

    const duration = typeof input.durationMs === 'number' ? input.durationMs : 3000;
    timersRef.current[id] = window.setTimeout(() => dismiss(id), duration);
  }, [dismiss]);

  const api = useMemo<ToastApi>(() => {
    return {
      show,
      success: (title, description) => show({ title, description, variant: 'success' }),
      error: (title, description) => show({ title, description, variant: 'error' }),
      warning: (title, description) => show({ title, description, variant: 'warning' }),
      info: (title, description) => show({ title, description, variant: 'info' }),
    };
  }, [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.viewport}>
        {items.map((t) => (
          <div key={t.id} className={styles.toast} role="status" aria-live="polite">
            <div className={`${styles.bar} ${VariantBarClass[t.variant]}`} />
            <div className={styles.content}>
              <div className={styles.titleRow}>
                <div className={styles.title}>{t.title}</div>
              </div>
              {t.description ? <div className={styles.desc}>{t.description}</div> : null}
            </div>
            <button className={styles.close} onClick={() => dismiss(t.id)} aria-label="关闭">
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

