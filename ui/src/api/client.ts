import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const client = axios.create({
  baseURL: BASE_URL,
});

export interface Workflow {
  id: string;
  name: string;
  description: string;
  state: string;
  agent_count: number;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDetail {
  id: string;
  name: string;
  description: string;
  config: any;
  tree: {
    root_id: string;
    nodes: Record<string, any>;
  };
  state: string;
}

export interface ExecutionResult {
  workflow_id: string;
  execution_id: string;
  state: string;
  output?: string;
  error?: string;
  duration_ms?: number;
}

// Built-in agent types
export interface ToolParameter {
  name: string;
  type: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'object';
  description: string;
  required: boolean;
  default?: any;
  enum?: string[];
}

export interface BuiltinTool {
  name: string;
  description: string;
  tool_type: 'http' | 'code' | 'transform';
  parameters: ToolParameter[];
  http_method?: string;
  http_url?: string;
  http_headers?: Record<string, string>;
  http_body_template?: string;
  code?: string;
  code_language?: string;
  input_mapping?: Record<string, string>;
  output_mapping?: Record<string, string>;
  timeout: number;
  retry_count?: number;
  approval_required?: boolean;
}

export interface OutputFormat {
  format_type?: 'text' | 'json' | 'markdown' | 'structured';
  json_schema?: any;
  structured_fields?: any[];
  example?: string;
}

export interface AgentDefinition {
  [key: string]: any;
  name: string;
  description: string;
  avatar?: string;
  category: string;
  provider: string;
  model: string;
  base_url?: string;
  api_key?: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  system_prompt: string;
  task_prompt_template?: string;
  output_instructions?: string;
  output_format?: OutputFormat;
  builtin_tools: BuiltinTool[];
  system_tools: string[];  // List of enabled system tool names
  knowledge_base?: string;
  context_window_strategy: string;
  max_context_messages: number;
  streaming_enabled: boolean;
  tool_choice: string;
  parallel_tool_calls: boolean;
  content_filter_enabled: boolean;
  max_output_tokens: number;
  tags: string[];
  version: string;
  builtin_definition?: Record<string, any>;
  routing_strategy?: string;
  max_depth?: number;
  timeout?: number;
  enabled?: boolean;
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  preview_image?: string;
  definition: AgentDefinition;
  popularity: number;
  is_official: boolean;
  author: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  is_official: boolean;
  agent_count: number;
}

export interface WorkflowTemplateDetail extends WorkflowTemplate {
  agents: Array<{
    ref_id: string;
    template_id: string;
    name: string;
    description: string;
    parent_ref: string | null;
    icon: string;
  }>;
}

export interface CreateWorkflowFromTemplateResult {
  status: string;
  workflow_id: string;
  name: string;
  agent_count: number;
  agents: Array<{
    ref_id: string;
    agent_id: string;
  }>;
}

export interface SystemTool {
  name: string;
  description: string;
  category: string;
  parameters: ToolParameter[];
  requires_approval: boolean;
  is_dangerous: boolean;
}

export interface SystemToolsResponse {
  tools: SystemTool[];
  categories: string[];
}

// Execution Event types for workflow visualization
export type ExecutionEventType =
  | 'workflow_start'
  | 'workflow_complete'
  | 'workflow_error'
  | 'node_start'
  | 'node_thinking'
  | 'node_tool_call'
  | 'node_tool_result'
  | 'node_complete'
  | 'node_error'
  | 'routing_start';

export interface ToolCallData {
  id: string;
  name: string;
  arguments: Record<string, any>;
}

export interface ToolResultData {
  tool_call_id: string;
  content: string;
  is_error: boolean;
}

export interface ExecutionEvent {
  event_type: ExecutionEventType;
  timestamp: number;
  workflow_id: string;
  execution_id: string;
  node_id?: string;
  node_name?: string;
  depth?: number;
  content?: string;
  delta_content?: string;
  tool_call?: ToolCallData;
  tool_result?: ToolResultData;
  routing_strategy?: string;
  target_nodes?: string[];
  status?: string;
  error?: string;
  duration_ms?: number;
  metadata?: Record<string, any>;
}

export interface TestAgentResult {
  response?: { messages?: Array<{ content: string }> } | string;
  error?: string;
  messages?: any[];
  metadata?: any;
}

// Copilot types
export interface CopilotMessage {
  role: string;
  content: string;
  timestamp: string;
}

export interface CopilotConfig {
  provider: string;
  model: string;
  base_url: string | null;
  api_key_configured: boolean;
  api_key_preview: string | null;
  available_models: string[];
  providers: string[];
  is_workflow_level?: boolean;
}

export interface CopilotSession {
  session_id: string;
  workflow_id?: string;
  messages: CopilotMessage[];
  created_at: string;
  updated_at: string;
}

export type CopilotEventType =
  | 'content'
  | 'tool_start'
  | 'tool_result'
  | 'workflow_created'
  | 'workflow_updated'
  | 'complete'
  | 'error';

export interface CopilotEvent {
  type: CopilotEventType;
  delta?: string;
  tool_name?: string;
  tool_args?: Record<string, any>;
  result?: Record<string, any>;
  workflow_id?: string;
  error?: string;
  timestamp?: string;
}

// Publishing types
export interface PublishedWorkflow {
  workflow_id: string;
  name: string;
  description: string;
  version: string;
  tags: string[];
  published_at: string;
  endpoint: string;
}

export interface PublishResult {
  workflow_id: string;
  api_key: string;
  version: string;
  endpoint: string;
}

// Search Config types
export interface SearchProviderInfo {
  id: string;
  name: string;
  description: string;
  configured: boolean;
  requires_api_key: boolean;
  requires_base_url?: boolean;
  china_accessible: boolean;
}

export interface SearchConfig {
  provider: string;
  searxng_base_url: string;
  searxng_configured: boolean;
  serper_configured: boolean;
  serper_api_key_preview: string | null;
  brave_configured: boolean;
  brave_api_key_preview: string | null;
  bing_configured: boolean;
  bing_api_key_preview: string | null;
  tavily_configured?: boolean;
  tavily_api_key_preview?: string | null;
  google_configured: boolean;
  available_providers: SearchProviderInfo[];
}

// Email Config types
export interface EmailConfig {
  preferred_method: string;
  active_method: string;
  resend: {
    configured: boolean;
    api_key_preview: string;
    from: string;
  };
  smtp: {
    configured: boolean;
    host: string;
    port: number;
    user: string;
    password_preview: string;
    from: string;
    use_tls: boolean;
  };
}

export const api = {
  // Workflows
  async listWorkflows(): Promise<Workflow[]> {
    const response = await client.get('/api/workflows');
    return response.data;
  },

  async getWorkflow(id: string): Promise<WorkflowDetail> {
    const response = await client.get(`/api/workflows/${id}`);
    return response.data;
  },

  async createWorkflow(data: { name: string; description?: string }): Promise<Workflow> {
    const response = await client.post('/api/workflows', data);
    return response.data;
  },

  async deleteWorkflow(id: string): Promise<void> {
    await client.delete(`/api/workflows/${id}`);
  },

  async runWorkflow(id: string, message: string): Promise<ExecutionResult> {
    const response = await client.post(`/api/workflows/${id}/run`, {
      message,
      stream: false,
    });
    return response.data;
  },

  runWorkflowStream(
    workflowId: string,
    message: string,
    onEvent: (event: ExecutionEvent) => void,
    onError?: (error: Error) => void,
    onComplete?: () => void,
  ): () => void {
    const abortController = new AbortController();

    const run = async () => {
      try {
        const response = await fetch(`${BASE_URL}/api/workflows/${workflowId}/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, stream: true }),
          signal: abortController.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

        const reader = response.body?.getReader();
        if (!reader) throw new Error('ReadableStream not supported');

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);
            if (data === '[DONE]') { onComplete?.(); return; }
            try { onEvent(JSON.parse(data)); } catch {}
          }
        }
        onComplete?.();
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        onError?.(err);
      }
    };

    run();
    return () => abortController.abort();
  },

  // Agents
  async addAgent(
    workflowId: string,
    data: {
      name: string;
      description?: string;
      type?: string;
      parent_id?: string;
      routing_strategy?: string;
    }
  ): Promise<any> {
    const response = await client.post(`/api/workflows/${workflowId}/agents`, data);
    return response.data;
  },

  async listAgents(workflowId: string): Promise<any[]> {
    const response = await client.get(`/api/workflows/${workflowId}/agents`);
    return response.data;
  },

  async removeAgent(workflowId: string, agentId: string): Promise<void> {
    await client.delete(`/api/workflows/${workflowId}/agents/${agentId}`);
  },

  async getAgentDefinition(workflowId: string, agentId: string): Promise<AgentDefinition> {
    const response = await client.get(`/api/workflows/${workflowId}/agents/${agentId}/definition`);
    return response.data;
  },

  async updateAgentDefinition(
    workflowId: string,
    agentId: string,
    definition: Partial<AgentDefinition>
  ): Promise<AgentDefinition> {
    const response = await client.put(
      `/api/workflows/${workflowId}/agents/${agentId}/definition`,
      definition
    );
    return response.data;
  },

  async addTool(workflowId: string, agentId: string, tool: BuiltinTool): Promise<BuiltinTool> {
    const response = await client.post(
      `/api/workflows/${workflowId}/agents/${agentId}/tools`,
      tool
    );
    return response.data;
  },

  async deleteTool(workflowId: string, agentId: string, toolName: string): Promise<void> {
    await client.delete(`/api/workflows/${workflowId}/agents/${agentId}/tools/${toolName}`);
  },

  async testAgent(workflowId: string, agentId: string, message: string): Promise<TestAgentResult> {
    const response = await client.post(
      `/api/workflows/${workflowId}/agents/${agentId}/test`,
      { message }
    );
    return response.data;
  },

  // Templates
  async getTemplates(category?: string): Promise<AgentTemplate[]> {
    const params = category ? { category } : {};
    const response = await client.get('/api/templates', { params });
    return response.data;
  },

  async createAgentFromTemplate(
    workflowId: string,
    templateId: string,
    agentName: string,
    parentId?: string
  ): Promise<any> {
    const response = await client.post(`/api/workflows/${workflowId}/agents/from-template`, {
      template_id: templateId,
      agent_name: agentName,
      parent_id: parentId,
    });
    return response.data;
  },

  // Plugins
  async listPlugins(): Promise<any[]> {
    const response = await client.get('/api/plugins');
    return response.data;
  },

  async registerMCP(data: { name: string; command: string; args?: string[]; agent_id?: string }): Promise<any> {
    const response = await client.post('/api/plugins/mcp', data);
    return response.data;
  },

  async registerSkill(data: {
    name: string; description: string; module_path: string;
    function_name: string; agent_id?: string;
  }): Promise<any> {
    const response = await client.post('/api/plugins/skill', data);
    return response.data;
  },

  async registerRAG(data: { name: string; type?: string; connection_string?: string; agent_id?: string }): Promise<any> {
    const response = await client.post('/api/plugins/rag', data);
    return response.data;
  },

  async uploadSkill(file: File): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await client.post('/api/skills/upload', formData);
    return response.data;
  },

  async listSkills(): Promise<any[]> {
    const response = await client.get('/api/skills');
    return response.data;
  },

  async bindSkillToAgent(skillId: string, agentId: string): Promise<any> {
    const response = await client.post(`/api/skills/${skillId}/bind/${agentId}`);
    return response.data;
  },

  async unbindSkillFromAgent(skillId: string, agentId: string): Promise<any> {
    const response = await client.post(`/api/skills/${skillId}/unbind/${agentId}`);
    return response.data;
  },

  async getAgentSkills(agentId: string): Promise<any[]> {
    const response = await client.get(`/api/agents/${agentId}/skills`);
    return response.data;
  },

  async uninstallSkill(skillId: string): Promise<any> {
    const response = await client.delete(`/api/skills/${skillId}`);
    return response.data;
  },

  async removePlugin(id: string): Promise<void> {
    await client.delete(`/api/plugins/${id}`);
  },

  // Workflow Templates
  async listWorkflowTemplates(): Promise<WorkflowTemplate[]> {
    const response = await client.get('/api/workflow-templates');
    return response.data;
  },

  async getWorkflowTemplate(id: string): Promise<WorkflowTemplateDetail> {
    const response = await client.get(`/api/workflow-templates/${id}`);
    return response.data;
  },

  async createWorkflowFromTemplate(
    templateId: string,
    data?: { name?: string; description?: string }
  ): Promise<CreateWorkflowFromTemplateResult> {
    const response = await client.post(`/api/workflow-templates/${templateId}/create`, data || {});
    return response.data;
  },

  // System Tools
  async listSystemTools(): Promise<SystemToolsResponse> {
    const response = await client.get('/api/system-tools');
    return response.data;
  },

  async getSystemToolsByCategory(): Promise<{
    categories: string[];
    tools_by_category: Record<string, SystemTool[]>;
  }> {
    const response = await client.get('/api/system-tools/categories');
    return response.data;
  },

  // ============== Copilot API ==============

  async createCopilotSession(workflowId?: string | null): Promise<{ session_id: string }> {
    const response = await client.post('/api/copilot/sessions',
      workflowId ? { workflow_id: workflowId } : undefined
    );
    return response.data;
  },

  async getCopilotConfig(): Promise<CopilotConfig> {
    const response = await client.get('/api/copilot/config');
    return response.data;
  },

  async updateCopilotConfig(config: {
    provider?: string; model?: string; api_key?: string; base_url?: string;
  }): Promise<{ status: string; config: CopilotConfig }> {
    const response = await client.post('/api/copilot/config', config);
    return response.data;
  },

  async getWorkflowCopilotConfig(workflowId: string): Promise<CopilotConfig> {
    const response = await client.get(`/api/workflows/${workflowId}/copilot/config`);
    return response.data;
  },

  async updateWorkflowCopilotConfig(workflowId: string, config: {
    provider?: string; model?: string; api_key?: string; base_url?: string;
  }): Promise<{ status: string; config: CopilotConfig }> {
    const response = await client.post(`/api/workflows/${workflowId}/copilot/config`, config);
    return response.data;
  },

  async deleteWorkflowCopilotConfig(workflowId: string): Promise<{ status: string }> {
    const response = await client.delete(`/api/workflows/${workflowId}/copilot/config`);
    return response.data;
  },

  // ============== Search Config API ==============

  async getSearchConfig(): Promise<SearchConfig> {
    const response = await client.get('/api/search/config');
    return response.data;
  },

  async updateSearchConfig(config: {
    provider?: string; searxng_base_url?: string; serper_api_key?: string;
    brave_api_key?: string; bing_api_key?: string; tavily_api_key?: string; google_api_key?: string; google_cx?: string;
  }): Promise<{ status: string; config: SearchConfig }> {
    const response = await client.post('/api/search/config', config);
    return response.data;
  },

  async testSearch(query: string, provider?: string): Promise<{ query: string; provider: string | null; result: string }> {
    const params = new URLSearchParams({ query });
    if (provider) params.append('provider', provider);
    const response = await client.post(`/api/search/test?${params.toString()}`);
    return response.data;
  },

  // ============== Email Config API ==============

  async getEmailConfig(): Promise<EmailConfig> {
    const response = await client.get('/api/email/config');
    return response.data;
  },

  async updateEmailConfig(config: {
    preferred_method?: string; resend_api_key?: string; resend_from?: string;
    smtp_host?: string; smtp_port?: number; smtp_user?: string; smtp_password?: string;
    smtp_from?: string; smtp_use_tls?: boolean;
  }): Promise<{ status: string; config: EmailConfig }> {
    const response = await client.post('/api/email/config', config);
    return response.data;
  },

  async testEmail(to: string): Promise<{ status: string; message: string }> {
    const response = await client.post('/api/email/test', { to });
    return response.data;
  },

  async getCopilotSession(sessionId: string): Promise<CopilotSession> {
    const response = await client.get(`/api/copilot/sessions/${sessionId}`);
    return response.data;
  },

  copilotChat(
    sessionId: string,
    message: string,
    onEvent: (event: CopilotEvent) => void,
    onComplete?: () => void,
    onError?: (error: Error) => void,
  ): () => void {
    const abortController = new AbortController();

    const run = async () => {
      try {
        const response = await fetch(`${BASE_URL}/api/copilot/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, message, stream: true }),
          signal: abortController.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

        const reader = response.body?.getReader();
        if (!reader) throw new Error('ReadableStream not supported');

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);
            if (data === '[DONE]') { onComplete?.(); return; }
            try { onEvent(JSON.parse(data) as CopilotEvent); } catch {}
          }
        }
        onComplete?.();
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        onError?.(err);
      }
    };

    run();
    return () => abortController.abort();
  },

  async copilotChatSync(sessionId: string, message: string): Promise<{
    content: string; tool_results: any[]; workflow_id?: string;
  }> {
    const response = await client.post('/api/copilot/chat', {
      session_id: sessionId, message, stream: false,
    });
    return response.data;
  },

  // ============== Publishing API ==============

  async publishWorkflow(
    workflowId: string,
    config: { version?: string; description?: string; tags?: string[] }
  ): Promise<PublishResult> {
    const response = await client.post(`/api/workflows/${workflowId}/publish`, config);
    return response.data;
  },

  async unpublishWorkflow(workflowId: string): Promise<void> {
    await client.post(`/api/workflows/${workflowId}/unpublish`);
  },

  async listPublishedWorkflows(): Promise<PublishedWorkflow[]> {
    const response = await client.get('/api/published');
    return response.data;
  },

  async runPublishedWorkflow(apiKey: string, message: string): Promise<ExecutionResult> {
    const response = await client.post(`/api/published/${apiKey}/run`, { message, stream: false });
    return response.data;
  },

  runPublishedWorkflowStream(
    apiKey: string,
    message: string,
    onEvent: (event: ExecutionEvent) => void,
    onComplete?: () => void,
    onError?: (error: Error) => void,
  ): () => void {
    const abortController = new AbortController();

    const run = async () => {
      try {
        const response = await fetch(`${BASE_URL}/api/published/${apiKey}/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, stream: true }),
          signal: abortController.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

        const reader = response.body?.getReader();
        if (!reader) throw new Error('ReadableStream not supported');

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);
            if (data === '[DONE]') { onComplete?.(); return; }
            try { onEvent(JSON.parse(data)); } catch {}
          }
        }
        onComplete?.();
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        onError?.(err);
      }
    };

    run();
    return () => abortController.abort();
  },

  // ============== Gateway API ==============

  async gatewayRoute(message: string): Promise<ExecutionResult> {
    const response = await client.post('/api/gateway/route', { message, stream: false });
    return response.data;
  },

  gatewayRouteStream(
    message: string,
    onEvent: (event: ExecutionEvent) => void,
    onComplete?: () => void,
    onError?: (error: Error) => void,
  ): () => void {
    const abortController = new AbortController();

    const run = async () => {
      try {
        const response = await fetch(`${BASE_URL}/api/gateway/route`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, stream: true }),
          signal: abortController.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

        const reader = response.body?.getReader();
        if (!reader) throw new Error('ReadableStream not supported');

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);
            if (data === '[DONE]') { onComplete?.(); return; }
            try { onEvent(JSON.parse(data)); } catch {}
          }
        }
        onComplete?.();
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        onError?.(err);
      }
    };

    run();
    return () => abortController.abort();
  },

  // ============== Portal (Super Portal) API ==============

  async listPortals(): Promise<any[]> {
    const response = await client.get('/api/portals');
    return response.data;
  },

  async getPortal(id: string): Promise<any> {
    const response = await client.get(`/api/portals/${id}`);
    return response.data;
  },

  async createPortal(data: {
    name: string;
    description?: string;
    workflow_ids: string[];
    provider?: string;
    model?: string;
    api_key?: string;
    base_url?: string;
    memory_enabled?: boolean;
  }): Promise<any> {
    const response = await client.post('/api/portals', data);
    return response.data;
  },

  async updatePortal(id: string, updates: Record<string, any>): Promise<any> {
    const response = await client.put(`/api/portals/${id}`, updates);
    return response.data;
  },

  async deletePortal(id: string): Promise<void> {
    await client.delete(`/api/portals/${id}`);
  },

  async createPortalSession(
    portalId: string,
    userId?: string
  ): Promise<{ session_id: string; portal_id: string }> {
    const response = await client.post(`/api/portals/${portalId}/sessions`, {
      user_id: userId ?? 'default',
    });
    return response.data;
  },

  async getPortalMemories(
    portalId: string,
    userId?: string,
    query?: string,
    topK?: number
  ): Promise<any[]> {
    const params: any = { user_id: userId ?? 'default' };
    if (query) params.query = query;
    if (topK) params.top_k = topK;
    const response = await client.get(`/api/portals/${portalId}/memories`, { params });
    return response.data;
  },

  async deletePortalMemory(portalId: string, entryId: string): Promise<any> {
    const response = await client.delete(`/api/portals/${portalId}/memories/${entryId}`);
    return response.data;
  },

  async clearPortalMemories(portalId: string, userId?: string): Promise<any> {
    const response = await client.delete(`/api/portals/${portalId}/memories`, {
      params: { user_id: userId ?? 'default' },
    });
    return response.data;
  },
};
