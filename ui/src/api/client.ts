import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
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
  format_type: 'text' | 'json' | 'markdown' | 'structured';
  json_schema?: any;
  structured_fields?: any[];
  example?: string;
}

export interface AgentDefinition {
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

export interface TestAgentResult {
  response?: string;
  error?: string;
  messages: any[];
  metadata: any;
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

  // Agent Definition (for builtin agents)
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

  // Built-in Tools
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

  // Agent Testing
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

  async registerMCP(data: {
    name: string;
    command: string;
    args?: string[];
    agent_id?: string;
  }): Promise<any> {
    const response = await client.post('/api/plugins/mcp', data);
    return response.data;
  },

  async registerSkill(data: {
    name: string;
    description: string;
    module_path: string;
    function_name: string;
    agent_id?: string;
  }): Promise<any> {
    const response = await client.post('/api/plugins/skill', data);
    return response.data;
  },

  async registerRAG(data: {
    name: string;
    type?: string;
    connection_string?: string;
    agent_id?: string;
  }): Promise<any> {
    const response = await client.post('/api/plugins/rag', data);
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
};
