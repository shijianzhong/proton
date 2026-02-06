import React, { useState } from 'react';
import { FiGrid, FiList, FiCpu, FiSettings } from 'react-icons/fi';
import WorkflowEditor from './components/WorkflowEditor';
import WorkflowList from './components/WorkflowList';
import SettingsPanel from './components/SettingsPanel';
import styles from './App.module.css';

const App: React.FC = () => {
  const [selectedMenu, setSelectedMenu] = useState('editor');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);

  const menuItems = [
    { key: 'editor', label: '工作流编辑器', icon: <FiGrid /> },
    { key: 'workflows', label: '工作流列表', icon: <FiList /> },
    { key: 'plugins', label: '插件管理', icon: <FiCpu /> },
    { key: 'settings', label: '系统设置', icon: <FiSettings /> },
  ];

  const renderContent = () => {
    switch (selectedMenu) {
      case 'editor':
        return (
          <WorkflowEditor
            workflowId={selectedWorkflowId}
            onWorkflowCreated={(id) => setSelectedWorkflowId(id)}
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
      case 'plugins':
        return <div className={styles.placeholder}>插件管理功能即将推出...</div>;
      case 'settings':
        return (
          <SettingsPanel
            visible={true}
            isPage={true}
            onClose={() => setSelectedMenu('editor')}
          />
        );
      default:
        return null;
    }
  };

  return (
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
              onClick={() => setSelectedMenu(key)}
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
  );
};

export default App;
