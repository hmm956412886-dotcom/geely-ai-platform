export interface HostContext {
  project_id: string;
  run_id: string;
  source_file: string;
  target_file: string;
  current_view: string;
  user_id: string;
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
