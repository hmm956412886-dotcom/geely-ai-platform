import type {
  AnalysisResponse,
  CompareResponse,
  GatewayErrorBody,
  HostContext,
  InsightsResponse,
} from "./types";

export class GatewayRequestError extends Error {
  readonly requestId?: string;

  constructor(message: string, requestId?: string) {
    super(message);
    this.name = "GatewayRequestError";
    this.requestId = requestId;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const payload = (await response.json()) as T & GatewayErrorBody;
  if (!response.ok) {
    throw new GatewayRequestError(
      payload.error?.message ?? `Gateway request failed (${response.status})`,
      payload.request_id,
    );
  }
  return payload;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const gatewayClient = {
  async getHostContext(): Promise<HostContext> {
    const payload = await requestJson<{ result: HostContext }>("/api/v1/host/context");
    return payload.result;
  },

  analyze(question: string, context: HostContext): Promise<AnalysisResponse> {
    return postJson<AnalysisResponse>("/api/v1/analyze", {
      question,
      project_id: context.project_id,
      source_file: context.source_file,
    });
  },

  insights(context: HostContext): Promise<InsightsResponse> {
    return postJson<InsightsResponse>("/api/v1/test-data/insights", {
      source_file: context.source_file,
    });
  },

  compare(context: HostContext): Promise<CompareResponse> {
    return postJson<CompareResponse>("/api/v1/test-data/compare", {
      baseline_file: context.source_file,
      target_file: context.target_file,
    });
  },
};
