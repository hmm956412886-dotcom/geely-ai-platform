export interface HostContext {
  host_session_id: string;
  project_id: string;
  run_id: string;
  source_asset_id?: string;
  target_asset_id?: string;
  baseline_asset_id?: string;
  source_file?: string;
  target_file?: string;
  current_view: string;
  user_id: string;
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
