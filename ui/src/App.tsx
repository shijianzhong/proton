import React, { useState } from 'react';
import { FiGrid, FiList, FiCpu, FiSettings } from 'react-icons/fi';
import WorkflowEditor from './components/WorkflowEditor';
import WorkflowList from './components/WorkflowList';
import styles from './App.module.css';

const App: React.FC = () => {
  const [selectedMenu, setSelectedMenu] = useState('editor');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);

  const menuItems = [
    { key: 'editor', label: 'Workflow Editor', icon: <FiGrid /> },
    { key: 'workflows', label: 'Workflows', icon: <FiList /> },
    { key: 'plugins', label: 'Plugins', icon: <FiCpu /> },
    { key: 'settings', label: 'Settings', icon: <FiSettings /> },
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
        return <div className={styles.placeholder}>Plugins management coming soon...</div>;
      case 'settings':
        return <div className={styles.placeholder}>Settings coming soon...</div>;
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
