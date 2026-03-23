import React, { useState } from 'react';
import { FiList, FiCpu, FiSettings, FiZap } from 'react-icons/fi';
import WorkflowEditor from './components/WorkflowEditor';
import WorkflowList from './components/WorkflowList';
import SettingsPanel from './components/SettingsPanel';
import PortalList from './components/PortalList';
import PortalChat from './components/PortalChat';
import type { Portal } from './components/PortalList';
import { ToastProvider } from './components/ToastProvider';
import styles from './App.module.css';

const App: React.FC = () => {
  const [selectedMenu, setSelectedMenu] = useState('workflows');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [chatPortal, setChatPortal] = useState<Portal | null>(null);

  const menuItems = [
    { key: 'workflows', label: '工作流列表',   icon: <FiList /> },
    { key: 'portals',   label: '超级入口',     icon: <FiZap /> },
    { key: 'plugins',   label: '插件管理',     icon: <FiCpu /> },
    { key: 'settings',  label: '系统设置',     icon: <FiSettings /> },
  ];

  const handleOpenChat = (portal: Portal) => {
    setChatPortal(portal);
    setSelectedMenu('portals');
  };

  const renderContent = () => {
    switch (selectedMenu) {
      case 'editor':
        return (
          <WorkflowEditor
            workflowId={selectedWorkflowId}
            onWorkflowCreated={(id) => {
              setSelectedWorkflowId(id);
              setSelectedMenu('editor');
            }}
          />
        );

      case 'workflows':
        return (
          <WorkflowList
            onSelect={(id) => {
              setSelectedWorkflowId(id);
              setSelectedMenu('editor');
            }}
          />
        );

      case 'portals':
        // If a portal chat is open, show the chat view
        if (chatPortal) {
          return (
            <PortalChat
              portal={chatPortal}
              onBack={() => setChatPortal(null)}
            />
          );
        }
        return (
          <PortalList
            onOpenChat={handleOpenChat}
          />
        );

      case 'plugins':
        return <div className={styles.placeholder}>插件管理功能即将推出...</div>;

      case 'settings':
        return (
          <SettingsPanel
            visible={true}
            isPage={true}
            onClose={() => setSelectedMenu('workflows')}
          />
        );

      default:
        return null;
    }
  };

  return (
    <ToastProvider>
      <div className={styles.app}>
        <aside className={styles.sidebar}>
          <header className={styles.header}>
            <h1 className={styles.title}>Proton</h1>
          </header>
          <nav className={styles.nav}>
            {menuItems.map(({ key, label, icon }) => (
              <div
                key={key}
                className={`${styles.navItem} ${selectedMenu === key ? styles.navItemSelected : ''}`}
                onClick={() => {
                  // If switching away from portals, clear the chat state
                  if (key !== 'portals') setChatPortal(null);
                  setSelectedMenu(key);
                }}
              >
                <span style={{ marginRight: '10px', width: '15px' }}>{icon}</span>
                {label}
              </div>
            ))}
          </nav>
        </aside>
        <main className={styles.content}>
          {renderContent()}
        </main>
      </div>
    </ToastProvider>
  );
};

export default App;
