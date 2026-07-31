import type {
  AgentActivity,
  AgentFileDiff,
  AgentPermission,
  CopilotAttachment,
  CopilotHistoryMessage,
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

  async diff(conversationId: string): Promise<AgentFileDiff[]> {
    const payload = await postJson<{ result: { files: AgentFileDiff[] } }>(
      sessionPath("/api/v1/agent/diff"),
      { conversation_id: conversationId },
    );
    return payload.result.files;
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
