import React, { useState, useEffect, useRef, useCallback } from 'react';
import { api, ExecutionEvent } from '../api/client';
import styles from './ExecutionPanel.module.css';

interface NodeState {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  depth: number;
  content: string;
  toolCalls: Array<{ id: string; name: string; arguments: Record<string, any> }>;
  toolResults: Array<{ tool_call_id: string; content: string; is_error: boolean }>;
  duration_ms?: number;
  error?: string;
}

interface ExecutionPanelProps {
  visible: boolean;
  workflowId: string | null;
  workflowName: string;
  onClose: () => void;
}

type WorkflowStatus = 'idle' | 'running' | 'completed' | 'error';

const ExecutionPanel: React.FC<ExecutionPanelProps> = ({
  visible,
  workflowId,
  workflowName,
  onClose,
}) => {
  const [inputMessage, setInputMessage] = useState('');
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>('idle');
  const [nodes, setNodes] = useState<Map<string, NodeState>>(new Map());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [finalResult, setFinalResult] = useState<string>('');
  const [workflowError, setWorkflowError] = useState<string>('');
  const [executionId, setExecutionId] = useState<string>('');

  const cancelRef = useRef<(() => void) | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Auto-scroll thinking content
  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [nodes, selectedNodeId]);

  // Reset state when panel closes
  useEffect(() => {
    if (!visible) {
      // Keep state for review, but allow cancel
      if (cancelRef.current) {
        cancelRef.current();
        cancelRef.current = null;
      }
    }
  }, [visible]);

  const handleEvent = useCallback((event: ExecutionEvent) => {
    switch (event.event_type) {
      case 'workflow_start':
        setExecutionId(event.execution_id);
        setWorkflowStatus('running');
        setNodes(new Map());
        setFinalResult('');
        setWorkflowError('');
        break;

      case 'workflow_complete':
        setWorkflowStatus('completed');
        // Collect final result from all completed nodes
        setNodes(prev => {
          const allContent: string[] = [];
          prev.forEach(node => {
            if (node.status === 'completed' && node.content) {
              allContent.push(`【${node.name}】\n${node.content}`);
            }
          });
          if (allContent.length > 0) {
            setFinalResult(allContent.join('\n\n---\n\n'));
          }
          return prev;
        });
        break;

      case 'workflow_error':
        setWorkflowStatus('error');
        setWorkflowError(event.error || 'Unknown error');
        break;

      case 'node_start':
        if (event.node_id && event.node_name) {
          setNodes(prev => {
            const newMap = new Map(prev);
            newMap.set(event.node_id!, {
              id: event.node_id!,
              name: event.node_name!,
              status: 'running',
              depth: event.depth || 0,
              content: '',
              toolCalls: [],
              toolResults: [],
            });
            return newMap;
          });
          // Auto-select newly started node
          setSelectedNodeId(event.node_id);
        }
        break;

      case 'node_thinking':
        if (event.node_id && event.delta_content) {
          setNodes(prev => {
            const newMap = new Map(prev);
            const node = newMap.get(event.node_id!);
            if (node) {
              newMap.set(event.node_id!, {
                ...node,
                content: node.content + event.delta_content,
              });
            }
            return newMap;
          });
        }
        break;

      case 'node_tool_call':
        if (event.node_id && event.tool_call) {
          setNodes(prev => {
            const newMap = new Map(prev);
            const node = newMap.get(event.node_id!);
            if (node) {
              newMap.set(event.node_id!, {
                ...node,
                toolCalls: [...node.toolCalls, event.tool_call!],
              });
            }
            return newMap;
          });
        }
        break;

      case 'node_tool_result':
        if (event.node_id && event.tool_result) {
          setNodes(prev => {
            const newMap = new Map(prev);
            const node = newMap.get(event.node_id!);
            if (node) {
              newMap.set(event.node_id!, {
                ...node,
                toolResults: [...node.toolResults, event.tool_result!],
              });
            }
            return newMap;
          });
        }
        break;

      case 'node_tool_result':
        if (event.node_id && event.tool_result) {
          setNodes(prev => {
            const newMap = new Map(prev);
            const node = newMap.get(event.node_id!);
            if (node) {
              newMap.set(event.node_id!, {
                ...node,
                toolResults: [...node.toolResults, event.tool_result!],
              });
            }
            return newMap;
          });
        }
        break;

      case 'node_complete':
        if (event.node_id) {
          setNodes(prev => {
            const newMap = new Map(prev);
            const node = newMap.get(event.node_id!);
            if (node) {
              newMap.set(event.node_id!, {
                ...node,
                status: 'completed',
                content: event.content || node.content,
                duration_ms: event.duration_ms,
              });
            }
            return newMap;
          });
        }
        break;

      case 'node_error':
        if (event.node_id) {
          setNodes(prev => {
            const newMap = new Map(prev);
            const node = newMap.get(event.node_id!);
            if (node) {
              newMap.set(event.node_id!, {
                ...node,
                status: 'error',
                error: event.error,
              });
            }
            return newMap;
          });
        }
        break;

      case 'routing_start':
        // Could visualize routing decisions
        break;
    }
  }, []);

  const handleRun = useCallback(() => {
    if (!workflowId || !inputMessage.trim()) return;

    // Reset state
    setNodes(new Map());
    setFinalResult('');
    setWorkflowError('');
    setSelectedNodeId(null);
    setWorkflowStatus('running');

    // Start streaming
    const cancel = api.runWorkflowStream(
      workflowId,
      inputMessage.trim(),
      handleEvent,
      (error) => {
        setWorkflowStatus('error');
        setWorkflowError(error.message);
      },
      () => {
        // Stream complete
        cancelRef.current = null;
      }
    );

    cancelRef.current = cancel;
  }, [workflowId, inputMessage, handleEvent]);

  const handleCancel = useCallback(() => {
    if (cancelRef.current) {
      cancelRef.current();
      cancelRef.current = null;
      setWorkflowStatus('idle');
    }
  }, []);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && workflowStatus !== 'running') {
      e.preventDefault();
      handleRun();
    }
  };

  const selectedNode = selectedNodeId ? nodes.get(selectedNodeId) : null;
  const nodesList = Array.from(nodes.values()).sort((a, b) => {
    // Sort by depth, then by order of appearance
    if (a.depth !== b.depth) return a.depth - b.depth;
    return 0;
  });

  const getStatusClass = (status: NodeState['status']) => {
    switch (status) {
      case 'pending': return styles.statusPending;
      case 'running': return styles.statusRunning;
      case 'completed': return styles.statusCompleted;
      case 'error': return styles.statusError;
    }
  };

  const getWorkflowStatusClass = () => {
    switch (workflowStatus) {
      case 'idle': return styles.workflowStatusIdle;
      case 'running': return styles.workflowStatusRunning;
      case 'completed': return styles.workflowStatusCompleted;
      case 'error': return styles.workflowStatusError;
    }
  };

  const formatDuration = (ms?: number) => {
    if (ms === undefined) return '';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <>
      {/* Overlay */}
      <div
        className={`${styles.overlay} ${visible ? styles.overlayVisible : ''}`}
        onClick={onClose}
      />

      {/* Panel */}
      <div className={`${styles.panel} ${visible ? styles.panelVisible : ''}`}>
        {/* Header */}
        <div className={styles.panelHeader}>
          <div>
            <h3 className={styles.panelTitle}>
              运行: {workflowName || '工作流'}
            </h3>
            <span className={`${styles.workflowStatus} ${getWorkflowStatusClass()}`}>
              {workflowStatus === 'running' && '● '}
              {workflowStatus.charAt(0).toUpperCase() + workflowStatus.slice(1)}
              {executionId && workflowStatus !== 'idle' && (
                <span style={{ opacity: 0.6, marginLeft: 8 }}>ID: {executionId.slice(0, 8)}</span>
              )}
            </span>
          </div>
          <button className={styles.closeButton} onClick={onClose}>×</button>
        </div>

        {/* Body */}
        <div className={styles.panelBody}>
          {/* Input Section */}
          <div className={styles.inputSection}>
            <div className={styles.inputWrapper}>
              <textarea
                className={styles.inputTextarea}
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="输入消息给工作流..."
                disabled={workflowStatus === 'running'}
                rows={2}
              />
              <div className={styles.inputButtons}>
                {workflowStatus === 'running' ? (
                  <button className={styles.cancelButton} onClick={handleCancel}>
                    取消
                  </button>
                ) : (
                  <button
                    className={styles.runButton}
                    onClick={handleRun}
                    disabled={!inputMessage.trim() || !workflowId}
                  >
                    运行
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Content Layout */}
          <div className={styles.contentLayout}>
            {/* Timeline */}
            <div className={styles.timelineSection}>
              <div className={styles.timelineHeader}>执行时间线</div>
              <div className={styles.timelineList}>
                {nodesList.length === 0 ? (
                  <div style={{ padding: '16px', color: '#666', textAlign: 'center' }}>
                    运行工作流以查看执行时间线
                  </div>
                ) : (
                  nodesList.map((node) => (
                    <div
                      key={node.id}
                      className={`${styles.timelineItem} ${selectedNodeId === node.id ? styles.timelineItemSelected : ''}`}
                      onClick={() => setSelectedNodeId(node.id)}
                      style={{ paddingLeft: `${16 + node.depth * 16}px` }}
                    >
                      <div className={styles.timelineItemHeader}>
                        <span className={`${styles.nodeStatus} ${getStatusClass(node.status)}`} />
                        <span className={styles.nodeName}>{node.name}</span>
                        {node.depth > 0 && (
                          <span className={styles.nodeDepth}>L{node.depth}</span>
                        )}
                      </div>
                      {node.duration_ms !== undefined && (
                        <div className={styles.nodeDuration}>
                          {formatDuration(node.duration_ms)}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Detail View */}
            <div className={styles.detailSection}>
              {selectedNode ? (
                <>
                  <div className={styles.detailHeader}>
                    <h4 className={styles.detailTitle}>{selectedNode.name}</h4>
                    <div className={styles.detailMeta}>
                      状态: {selectedNode.status}
                      {selectedNode.duration_ms !== undefined && (
                        <> · 耗时: {formatDuration(selectedNode.duration_ms)}</>
                      )}
                    </div>
                  </div>
                  <div className={styles.detailContent} ref={contentRef}>
                    {/* Thinking Content */}
                    {selectedNode.content && (
                      <div className={styles.thinkingContent}>
                        {selectedNode.content}
                        {selectedNode.status === 'running' && (
                          <span className={styles.cursor} />
                        )}
                      </div>
                    )}

                    {/* Tool Calls */}
                    {selectedNode.toolCalls.length > 0 && (
                      <div className={styles.toolCallsSection}>
                        <div className={styles.sectionTitle}>工具调用</div>
                        {selectedNode.toolCalls.map((tc, idx) => (
                          <div key={idx} className={styles.toolCallCard}>
                            <div className={styles.toolCallHeader}>
                              <span className={styles.toolCallIcon}>🔧</span>
                              <span className={styles.toolCallName}>{tc.name}</span>
                            </div>
                            <pre className={styles.toolCallArgs}>
                              {JSON.stringify(tc.arguments, null, 2)}
                            </pre>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Tool Results */}
                    {selectedNode.toolResults.length > 0 && (
                      <div className={styles.toolCallsSection}>
                        <div className={styles.sectionTitle}>工具结果</div>
                        {selectedNode.toolResults.map((tr, idx) => (
                          <div key={idx} className={styles.toolResultCard}>
                            <pre className={styles.toolResultContent}>
                              {tr.content}
                            </pre>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Error */}
                    {selectedNode.error && (
                      <div className={styles.errorSection}>
                        <div className={styles.errorTitle}>
                          ⚠️ 错误
                        </div>
                        <div className={styles.errorContent}>
                          {selectedNode.error}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className={styles.emptyState}>
                  <div className={styles.emptyStateIcon}>📊</div>
                  <p>选择时间线中的节点查看详情</p>
                  {finalResult && (
                    <div className={styles.finalResultSection} style={{ marginTop: 24, textAlign: 'left', width: '100%' }}>
                      <div className={styles.finalResultTitle}>
                        ✅ 最终结果
                      </div>
                      <div className={styles.finalResultContent}>
                        {finalResult}
                      </div>
                    </div>
                  )}
                  {workflowError && (
                    <div className={styles.errorSection} style={{ marginTop: 24, textAlign: 'left', width: '100%' }}>
                      <div className={styles.errorTitle}>⚠️ 工作流错误</div>
                      <div className={styles.errorContent}>{workflowError}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default ExecutionPanel;
