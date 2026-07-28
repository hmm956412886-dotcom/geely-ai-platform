import type {
  AgentResponse,
  CopilotAttachment,
  CopilotResponse,
  CompareResponse,
  GatewayErrorBody,
  HostContext,
  InsightsResponse,
} from "./types";

const querySessionId = new URLSearchParams(window.location.search).get("host_session_id");
const accessToken = new URLSearchParams(window.location.hash.slice(1)).get("access_token");
export const hostSessionId = querySessionId || "default";

function sessionPath(path: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}host_session_id=${encodeURIComponent(hostSessionId)}`;
}

export class GatewayRequestError extends Error {
  readonly requestId?: string;

  constructor(message: string, requestId?: string) {
    super(message);
    this.name = "GatewayRequestError";
    this.requestId = requestId;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(path, { ...init, headers });
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
    const payload = await requestJson<{ result: HostContext }>(sessionPath("/api/v1/host/context"));
    return payload.result;
  },

  async updateHostContext(context: Partial<HostContext>): Promise<HostContext> {
    const { host_session_id: _, ...payloadContext } = context;
    const payload = await postJson<{ result: HostContext }>(
      sessionPath("/api/v1/host/context"),
      payloadContext,
    );
    return payload.result;
  },

  queryAgent(question: string): Promise<AgentResponse> {
    return postJson<AgentResponse>(sessionPath("/api/v1/agent/query"), { question });
  },

  queryCopilot(
    question: string,
    attachments: CopilotAttachment[],
    task: "chat" | "generate_test" = "chat",
  ): Promise<CopilotResponse> {
    return postJson<CopilotResponse>(sessionPath("/api/v1/copilot/query"), {
      question,
      task,
      attachments: attachments.map(({ name, content }) => ({ name, content })),
    });
  },

  insights(context: HostContext): Promise<InsightsResponse> {
    const source = context.source_asset_id
      ? { source_asset_id: context.source_asset_id }
      : { source_file: context.source_file };
    return postJson<InsightsResponse>(sessionPath("/api/v1/test-data/insights"), source);
  },

  compare(context: HostContext): Promise<CompareResponse> {
    const sources = context.source_asset_id
      ? {
          baseline_asset_id: context.source_asset_id,
          target_asset_id: context.target_asset_id,
        }
      : { baseline_file: context.source_file, target_file: context.target_file };
    return postJson<CompareResponse>(sessionPath("/api/v1/test-data/compare"), sources);
  },
};
