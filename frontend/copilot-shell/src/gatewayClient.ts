import type {
  AgentActivity,
  AgentDiffResult,
  AgentPermission,
  CopilotAttachment,
  CopilotHistoryMessage,
  CopilotResponse,
  CopilotStreamEvent,
  CompareResponse,
  GatewayErrorBody,
  HostContext,
  InsightsResponse,
  ModelConfig,
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
  readonly code?: string;

  constructor(message: string, requestId?: string, code?: string) {
    super(message);
    this.name = "GatewayRequestError";
    this.requestId = requestId;
    this.code = code;
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
      payload.error?.code,
    );
  }
  return payload;
}

function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

async function postEventStream(
  path: string,
  body: unknown,
  onEvent: (event: CopilotStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json", Accept: "text/event-stream" });
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    const payload = (await response.json().catch(() => ({}))) as GatewayErrorBody;
    throw new GatewayRequestError(
      payload.error?.message ?? `Gateway stream failed (${response.status})`,
      payload.request_id,
      payload.error?.code,
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    while (buffer.includes("\n\n")) {
      const boundary = buffer.indexOf("\n\n");
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = block.split("\n").find((line) => line.startsWith("data:"))?.slice(5).trim();
      if (data) onEvent(JSON.parse(data) as CopilotStreamEvent);
    }
    if (done) break;
  }
}

export const gatewayClient = {
  async getModelConfig(): Promise<ModelConfig> {
    const payload = await requestJson<{ result: ModelConfig }>(
      sessionPath("/api/v1/model/config"),
    );
    return payload.result;
  },

  async updateModelConfig(update: {
    base_url?: string;
    api_key?: string;
    model?: string;
  }): Promise<ModelConfig> {
    const payload = await postJson<{ result: ModelConfig }>(
      sessionPath("/api/v1/model/config"),
      update,
    );
    return payload.result;
  },

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

  queryCopilot(
    question: string,
    conversationId: string,
    attachments: CopilotAttachment[],
    history: CopilotHistoryMessage[],
    task: "chat" | "generate_test" = "chat",
    signal?: AbortSignal,
  ): Promise<CopilotResponse> {
    return postJson<CopilotResponse>(sessionPath("/api/v1/copilot/query"), {
      question,
      conversation_id: conversationId,
      task,
      history,
      attachments: attachments.map(({ name, content }) => ({ name, content })),
    }, signal);
  },

  streamCopilot(
    question: string,
    conversationId: string,
    attachments: CopilotAttachment[],
    history: CopilotHistoryMessage[],
    onEvent: (event: CopilotStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    return postEventStream(sessionPath("/api/v1/copilot/stream"), {
      question,
      conversation_id: conversationId,
      task: "chat",
      history,
      attachments: attachments.map(({ name, content }) => ({ name, content })),
    }, onEvent, signal);
  },

  async pendingPermissions(conversationId: string): Promise<AgentPermission[]> {
    const payload = await postJson<{ result: { permissions: AgentPermission[] } }>(
      sessionPath("/api/v1/agent/permissions"),
      { conversation_id: conversationId },
    );
    return payload.result.permissions;
  },

  async activity(conversationId: string): Promise<AgentActivity[]> {
    const payload = await postJson<{ result: { activity: AgentActivity[] } }>(
      sessionPath("/api/v1/agent/activity"),
      { conversation_id: conversationId },
    );
    return payload.result.activity;
  },

  async diff(conversationId: string): Promise<AgentDiffResult> {
    const payload = await postJson<{ result: AgentDiffResult }>(
      sessionPath("/api/v1/agent/diff"),
      { conversation_id: conversationId },
    );
    return payload.result;
  },

  async revert(conversationId: string): Promise<boolean> {
    const payload = await postJson<{ result: { reverted: boolean } }>(
      sessionPath("/api/v1/agent/revert"),
      { conversation_id: conversationId },
    );
    return payload.result.reverted;
  },

  replyPermission(
    conversationId: string,
    requestId: string,
    reply: "once" | "reject",
  ): Promise<unknown> {
    return postJson(sessionPath("/api/v1/agent/permissions/reply"), {
      conversation_id: conversationId,
      request_id: requestId,
      reply,
    });
  },

  abortConversation(conversationId: string): Promise<unknown> {
    return postJson(sessionPath("/api/v1/agent/abort"), {
      conversation_id: conversationId,
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
