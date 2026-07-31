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
