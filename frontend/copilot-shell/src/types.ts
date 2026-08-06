export interface HostContext {
  host_session_id: string;
  host_application?: string | null;
  project_id: string | null;
  project_label?: string | null;
  run_id: string | null;
  source_asset_id?: string | null;
  target_asset_id?: string | null;
  baseline_asset_id?: string | null;
  source_file?: string | null;
  target_file?: string | null;
  current_view: string | null;
  user_id: string | null;
  selection_kind?: string | null;
  selection_label?: string | null;
  snapshot_revision?: string | null;
}

export interface HostContextMessage {
  type: "geely-ai.host-context";
  host_session_id: string;
  context: Partial<Omit<HostContext, "host_session_id">>;
}

export interface GatewayErrorBody {
  request_id?: string;
  error?: {
    code: string;
    message: string;
  };
}

export interface AnalysisResponse {
  request_id: string;
  answer: string;
  citations: Array<{
    title: string;
    source_url: string;
    provider: string;
  }>;
  warnings: string[];
}

export interface CopilotAttachment {
  name: string;
  content: string;
  size: number;
}

export interface ModelConfig {
  provider: string;
  configured: boolean;
  base_url: string | null;
  model: string | null;
  available_models: string[];
  api_key_configured: boolean;
  timeout_seconds: number;
}

export interface ModelProviderModel {
  id: string;
  name: string;
}

export interface ModelProvider {
  id: string;
  name: string;
  base_url: string;
  models: ModelProviderModel[];
  api_key_configured: boolean;
  active: boolean;
}

export interface ModelProviderCatalog {
  providers: ModelProvider[];
  active_provider_id: string | null;
  active_model_id: string | null;
}

export interface CopilotHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface CopilotArtifact {
  name: string;
  language: string;
  content: string;
}

export interface CopilotResponse extends AnalysisResponse {
  artifacts: CopilotArtifact[];
}

export type CopilotStreamEvent =
  | { type: "started" }
  | { type: "text_delta"; delta: string; segment_id?: string }
  | { type: "reasoning_delta"; delta: string; segment_id?: string }
  | { type: "tool"; id: string; tool: string; status: string; title: string; output: string }
  | { type: "step"; id: string; status: string; title: string }
  | { type: "todo"; todos: AgentTodo[] }
  | { type: "retry"; attempt: number; message: string }
  | { type: "patch"; files: string[] }
  | { type: "permission"; permission: AgentPermission }
  | { type: "completed"; answer: string }
  | { type: "idle" }
  | { type: "error"; message: string; code?: string };

export interface AgentPermission {
  id: string;
  permission: string;
  resources: string[];
}

export interface AgentActivity {
  id: string;
  tool: string;
  status: string;
  title: string;
  output: string;
}

export type AgentTurnStatus = "idle" | "running" | "completed" | "failed" | "cancelled";

export interface AgentTodo {
  content: string;
  status: string;
  priority: string;
}

export interface AgentFileDiff {
  path: string;
  status: "added" | "deleted" | "modified";
  additions: number;
  deletions: number;
  patch: string;
  truncated: boolean;
}

export interface AgentDiffResult {
  files: AgentFileDiff[];
  revert_available: boolean;
  revert_reason: "no_turn" | "no_file_changes" | "workspace_has_no_git_baseline" | null;
}

export interface InsightsResponse {
  request_id: string;
  result: {
    engine: string;
    run_id: string;
    status_counts: Array<{ status: string; count: number }>;
    failure_reasons: Array<{ reason: string; count: number }>;
  };
}

export interface CompareResponse {
  request_id: string;
  result: Record<string, unknown>;
}
