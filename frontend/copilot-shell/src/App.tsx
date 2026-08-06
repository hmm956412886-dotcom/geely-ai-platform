import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  SimpleTextAttachmentAdapter,
  useExternalStoreRuntime,
  type AppendMessage,
  type CompleteAttachment,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import {
  Button,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  Field,
  FluentProvider,
  Input,
  OverlayDrawer,
  Spinner,
  Textarea,
  webLightTheme,
} from "@fluentui/react-components";
import {
  Add20Regular,
  CheckmarkCircle20Regular,
  Delete20Regular,
  Dismiss24Regular,
  Play20Regular,
} from "@fluentui/react-icons";
import { AgentThread } from "./AgentThread";
import { GatewayRequestError, gatewayClient, hostSessionId } from "./gatewayClient";
import type {
  AgentActivity,
  AgentDiffResult,
  AgentPermission,
  AgentTodo,
  AgentTurnStatus,
  CopilotArtifact,
  CopilotAttachment,
  CopilotHistoryMessage,
  CopilotResponse,
  HostContext,
  HostContextMessage,
  ModelProviderCatalog,
} from "./types";

interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
  attachments?: readonly CompleteAttachment[];
}

interface Conversation {
  id: string;
  projectKey: string;
  title: string;
  messages: ChatMessage[];
  artifacts: CopilotArtifact[];
  updatedAt: number;
}

interface RequestDiagnostic {
  detail: string;
  requestId?: string;
}

const emptyDiffResult: AgentDiffResult = {
  files: [],
  revert_available: false,
  revert_reason: "no_turn",
};

const parentOrigin = resolveParentOrigin();
const attachmentAccept = [
  ".py", ".json", ".yaml", ".yml", ".xml", ".txt", ".dbc", ".md",
  ".toml", ".ini", ".cfg", ".csv", ".log", ".asc",
].join(",");
const maxAttachments = 5;
const maxFileBytes = 256 * 1024;
const maxTotalBytes = 512 * 1024;
const agentLightTheme = {
  ...webLightTheme,
  colorBrandBackground: "#0b6f65",
  colorBrandBackgroundHover: "#085b53",
  colorBrandBackgroundPressed: "#064a44",
  colorBrandForeground1: "#0b6f65",
  colorBrandForegroundLink: "#096b9e",
  colorBrandStroke1: "#0b6f65",
  colorCompoundBrandForeground1: "#0b6f65",
  colorCompoundBrandStroke: "#0b6f65",
  colorNeutralStrokeFocus2: "#0b6f65",
};

const emptyContext: HostContext = {
  host_session_id: hostSessionId,
  project_id: null,
  run_id: null,
  current_view: null,
  user_id: null,
};

function assistantMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "assistant", content };
}

function userMessage(
  content: string,
  attachments?: readonly CompleteAttachment[],
): ChatMessage {
  return { id: crypto.randomUUID(), role: "user", content, attachments };
}

function parseProviderModels(value: string): Array<{ id: string; name: string }> {
  const models = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const separator = line.indexOf("|");
      const id = (separator >= 0 ? line.slice(0, separator) : line).trim();
      const name = (separator >= 0 ? line.slice(separator + 1) : line).trim() || id;
      if (!id) throw new Error("模型 ID 不能为空");
      return { id, name };
    });
  if (!models.length) throw new Error("请至少填写一个模型");
  if (new Set(models.map(({ id }) => id)).size !== models.length) {
    throw new Error("模型 ID 不能重复");
  }
  return models;
}

function createConversation(projectKey: string): Conversation {
  return {
    id: crypto.randomUUID(),
    projectKey,
    title: "新对话",
    messages: [],
    artifacts: [],
    updatedAt: Date.now(),
  };
}

function loadConversations(): Conversation[] {
  try {
    const raw = window.localStorage.getItem(`geely-ai.history.${hostSessionId}`);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is Conversation => Boolean(
        item && typeof item.id === "string" && typeof item.projectKey === "string"
        && typeof item.title === "string" && Array.isArray(item.messages)
        && Array.isArray(item.artifacts) && typeof item.updatedAt === "number",
      ))
      .map((conversation) => ({
        ...conversation,
        messages: conversation.messages.map((message) => message.role === "assistant"
          ? { ...message, content: message.content.replace(/^### AI 说明\s*/, "") }
          : message),
      }))
      .slice(-30);
  } catch {
    return [];
  }
}

function projectKey(context: HostContext): string {
  return `${context.host_application || "CoreTest"}:${context.project_id || "未打开工程"}`;
}

function conversationTitle(content: string): string {
  const title = content.replace(/\s+/g, " ").trim();
  return title.length > 24 ? `${title.slice(0, 24)}…` : title || "新对话";
}

function updatedTime(timestamp: number): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

function convertMessage(message: ChatMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    attachments: message.attachments,
    status:
      message.role === "assistant" ? { type: "complete", reason: "stop" } : undefined,
  };
}

function messageText(message: AppendMessage): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

async function messageAttachments(message: AppendMessage): Promise<CopilotAttachment[]> {
  const items = message.attachments ?? [];
  if (items.length > maxAttachments) throw new Error(`最多添加 ${maxAttachments} 个文件。`);
  let totalBytes = 0;
  return Promise.all(items.map(async (attachment) => {
    if (!attachment.file) throw new Error(`无法读取附件 ${attachment.name}。`);
    if (attachment.file.size > maxFileBytes) {
      throw new Error(`${attachment.name} 超过 256 KiB，无法添加。`);
    }
    totalBytes += attachment.file.size;
    if (totalBytes > maxTotalBytes) throw new Error("附件总大小不能超过 512 KiB。");
    try {
      const content = new TextDecoder("utf-8", { fatal: true }).decode(
        await attachment.file.arrayBuffer(),
      );
      return { name: attachment.name, content, size: attachment.file.size };
    } catch (error) {
      if (error instanceof Error && error.message.includes("KiB")) throw error;
      throw new Error(`${attachment.name} 不是有效的 UTF-8 文本文件。`);
    }
  }));
}

function conversationHistory(messages: ChatMessage[]): CopilotHistoryMessage[] {
  return messages.slice(-20).map(({ role, content }) => ({ role, content }));
}

function formatReferences(payload: CopilotResponse): string {
  const source = payload.citations.length
    ? `\n\n### 来源\n${payload.citations
        .map((citation) => `- [${citation.title}](${citation.source_url}) · ${citation.provider}`)
        .join("\n")}`
    : "";
  const warning = payload.warnings.length ? `\n\n> ${payload.warnings.join("；")}` : "";
  return `${source}${warning}`;
}

function formatCopilotResponse(payload: CopilotResponse): string {
  const generated = payload.artifacts
    .map((artifact) => `\n\n### ${artifact.name}\n\n\`\`\`${artifact.language}\n${artifact.content}\`\`\``)
    .join("");
  return `${payload.answer}${generated}${formatReferences(payload)}`;
}

function currentDataLabel(context: HostContext): string {
  const labels: Record<string, string> = {
    trace: "Trace",
    dbc: "DBC",
    diagnostic: "诊断数据",
    project: "当前工程",
    file: "工程文件",
    pdx: "PDX",
  };
  return labels[context.selection_kind ?? ""] ?? "当前内容";
}

function localizedError(error: unknown): string {
  if (error instanceof GatewayRequestError && error.code === "model_unavailable") {
    return "AI 模型尚未配置或当前不可用，请检查模型设置后重试。";
  }
  if (error instanceof GatewayRequestError && error.code === "agent_stalled") {
    return "智能体连续 5 分钟没有新进展，本轮已自动停止。可以直接重新发送任务。";
  }
  if (error instanceof GatewayRequestError && error.code === "agent_stream_disconnected") {
    return "智能体连接意外中断，本轮已停止。可以直接重试，系统会创建干净会话继续。";
  }
  if (error instanceof GatewayRequestError && error.code === "agent_timeout") {
    return "本轮任务已达到 30 分钟上限并自动停止。可以缩小任务范围后重新发送。";
  }
  if (error instanceof GatewayRequestError && error.code === "agent_failed") {
    return "智能体执行失败，本轮已停止。请查看诊断详情后重试。";
  }
  if (error instanceof TypeError && error.message.includes("fetch")) {
    return "无法连接 AI Gateway，请确认服务已启动。";
  }
  if (error instanceof GatewayRequestError) return "请求未能完成，请检查输入后重试。";
  return error instanceof Error ? error.message : "请求未能完成，请稍后重试。";
}

function isActiveStatus(status: string): boolean {
  return status === "running" || status === "pending" || status === "in_progress";
}

export default function App() {
  const [context, setContext] = useState<HostContext>(emptyContext);
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const saved = loadConversations();
    return saved.length ? saved : [createConversation(projectKey(emptyContext))];
  });
  const [activeConversationId, setActiveConversationId] = useState(() => conversations[0]?.id ?? "");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [turnStatus, setTurnStatus] = useState<AgentTurnStatus>("idle");
  const [composerAttachmentCount, setComposerAttachmentCount] = useState(0);
  const [diagnostic, setDiagnostic] = useState<RequestDiagnostic | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [permission, setPermission] = useState<AgentPermission | null>(null);
  const [permissionReplying, setPermissionReplying] = useState(false);
  const [activity, setActivity] = useState<AgentActivity[]>([]);
  const [reasoning, setReasoning] = useState("");
  const [todos, setTodos] = useState<AgentTodo[]>([]);
  const [diffResult, setDiffResult] = useState<AgentDiffResult>(emptyDiffResult);
  const [reverting, setReverting] = useState(false);
  const [modelProviders, setModelProviders] = useState<ModelProviderCatalog | null>(null);
  const [providerModels, setProviderModels] = useState<Record<string, string>>({});
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [providerIdDraft, setProviderIdDraft] = useState("");
  const [providerNameDraft, setProviderNameDraft] = useState("");
  const [providerUrlDraft, setProviderUrlDraft] = useState("");
  const [providerKeyDraft, setProviderKeyDraft] = useState("");
  const [providerModelsDraft, setProviderModelsDraft] = useState("");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [modelSaving, setModelSaving] = useState(false);
  const [testingProviderId, setTestingProviderId] = useState<string | null>(null);
  const activeConversationIdRef = useRef(activeConversationId);
  const abortControllerRef = useRef<AbortController | null>(null);
  const currentProjectKey = projectKey(context);
  const activeConversation = conversations.find(({ id }) => id === activeConversationId);
  const messages = activeConversation?.messages ?? [];
  const artifacts = activeConversation?.artifacts ?? [];
  const hostConnected = Boolean(context.host_application);
  const hasCurrentData = Boolean(context.selection_kind && context.snapshot_revision);
  const hasSelectedFile = context.selection_kind === "file" && hasCurrentData;
  const dataLabel = currentDataLabel(context);
  const latestAssistantId = [...messages].reverse()
    .find((message) => message.role === "assistant")?.id;
  const lastMessageRole = messages[messages.length - 1]?.role;
  const isRunning = turnStatus === "running";

  useEffect(() => {
    try {
      window.localStorage.setItem(
        `geely-ai.history.${hostSessionId}`,
        JSON.stringify(conversations.slice(-30)),
      );
    } catch {
      // Local history is best-effort and must not block the Agent.
    }
  }, [conversations]);

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
  }, [activeConversationId]);

  useEffect(() => {
    if (activeConversation?.projectKey === currentProjectKey) return;
    const latest = conversations
      .filter((conversation) => conversation.projectKey === currentProjectKey)
      .sort((left, right) => right.updatedAt - left.updatedAt)[0];
    if (latest) {
      setActiveConversationId(latest.id);
      return;
    }
    const conversation = createConversation(currentProjectKey);
    setConversations((current) => [...current, conversation]);
    setActiveConversationId(conversation.id);
  }, [activeConversation?.projectKey, conversations, currentProjectKey]);

  const attachmentAdapter = useMemo(() => {
    const adapter = new SimpleTextAttachmentAdapter();
    adapter.accept = attachmentAccept;
    return adapter;
  }, []);

  const appendMessage = useCallback((conversationId: string, message: ChatMessage) => {
    setConversations((current) => current.map((conversation) => {
      if (conversation.id !== conversationId) return conversation;
      return {
        ...conversation,
        title:
          conversation.title === "新对话" && message.role === "user"
            ? conversationTitle(message.content)
            : conversation.title,
        messages: [...conversation.messages, message],
        updatedAt: Date.now(),
      };
    }));
  }, []);

  const appendAssistant = useCallback((conversationId: string, content: string) => {
    appendMessage(conversationId, assistantMessage(content));
  }, [appendMessage]);

  const updateMessage = useCallback((conversationId: string, messageId: string, content: string) => {
    setConversations((current) => current.map((conversation) =>
      conversation.id === conversationId
        ? {
            ...conversation,
            messages: conversation.messages.map((message) =>
              message.id === messageId ? { ...message, content } : message
            ),
            updatedAt: Date.now(),
          }
        : conversation
    ));
  }, []);

  const reportError = useCallback(
    (error: unknown, conversationId = activeConversationIdRef.current) => {
      const requestId = error instanceof GatewayRequestError ? error.requestId : undefined;
      const detail = error instanceof Error ? error.message : "Unknown request error";
      setDiagnostic({ detail, requestId });
      appendAssistant(
        conversationId,
        `**请求未完成**\n\n${localizedError(error)}`,
      );
    },
    [appendAssistant],
  );

  const refreshContext = useCallback(async () => {
    try {
      setContext(await gatewayClient.getHostContext());
    } catch (error) {
      reportError(error);
    }
  }, [reportError]);

  const applyProviderCatalog = useCallback((catalog: ModelProviderCatalog) => {
    setModelProviders(catalog);
    setProviderModels((current) => Object.fromEntries(catalog.providers.map((provider) => {
      const selected = provider.id === catalog.active_provider_id
        ? catalog.active_model_id
        : current[provider.id];
      const model = provider.models.some(({ id }) => id === selected)
        ? selected!
        : provider.models[0]?.id ?? "";
      return [provider.id, model];
    })));
  }, []);

  const refreshModelProviders = useCallback(async () => {
    try {
      applyProviderCatalog(await gatewayClient.getModelProviders());
      setSettingsError(null);
    } catch (error) {
      setModelProviders(null);
      setSettingsError(error instanceof Error ? error.message : "Provider 列表加载失败");
    }
  }, [applyProviderCatalog]);

  useEffect(() => {
    void refreshModelProviders();
  }, [refreshModelProviders]);

  useEffect(() => {
    if (hostConnected) void refreshModelProviders();
  }, [hostConnected, refreshModelProviders]);

  const openSettings = useCallback(() => {
    setSettingsError(null);
    setSettingsOpen(true);
    void refreshModelProviders();
  }, [refreshModelProviders]);

  const saveProvider = useCallback(async () => {
    if (modelSaving) return;
    setSettingsError(null);
    setModelSaving(true);
    try {
      const models = parseProviderModels(providerModelsDraft);
      const next = await gatewayClient.saveModelProvider({
        id: providerIdDraft.trim(),
        name: providerNameDraft.trim(),
        base_url: providerUrlDraft.trim(),
        api_key: providerKeyDraft.trim(),
        models,
        activate: true,
      });
      applyProviderCatalog(next);
      setProviderIdDraft("");
      setProviderNameDraft("");
      setProviderUrlDraft("");
      setProviderKeyDraft("");
      setProviderModelsDraft("");
      setSaveNotice(`已保存并启用：${next.active_provider_id}/${next.active_model_id}`);
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : "Provider 保存失败");
    } finally {
      setModelSaving(false);
    }
  }, [
    applyProviderCatalog,
    modelSaving,
    providerIdDraft,
    providerKeyDraft,
    providerModelsDraft,
    providerNameDraft,
    providerUrlDraft,
  ]);

  const selectModel = useCallback(async (providerId: string, modelId: string) => {
    if (!providerId || !modelId || modelSaving) return;
    if (
      providerId === modelProviders?.active_provider_id
      && modelId === modelProviders.active_model_id
    ) return;
    setModelSaving(true);
    try {
      applyProviderCatalog(await gatewayClient.activateModelProvider(providerId, modelId));
      setSaveNotice(`已切换模型：${providerId}/${modelId}`);
    } catch (error) {
      reportError(error);
    } finally {
      setModelSaving(false);
    }
  }, [applyProviderCatalog, modelProviders, modelSaving, reportError]);

  const testProvider = useCallback(async (providerId: string) => {
    const modelId = providerModels[providerId];
    if (!modelId || modelSaving) return;
    setSettingsError(null);
    setModelSaving(true);
    setTestingProviderId(providerId);
    try {
      await gatewayClient.testModelProvider(providerId, modelId);
      setSaveNotice(`连接测试通过：${providerId}/${modelId}`);
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : "连接测试失败");
    } finally {
      setTestingProviderId(null);
      setModelSaving(false);
    }
  }, [modelSaving, providerModels]);

  const deleteProvider = useCallback(async (providerId: string) => {
    if (modelSaving || !window.confirm(`删除 Provider “${providerId}”？`)) return;
    setSettingsError(null);
    setModelSaving(true);
    try {
      applyProviderCatalog(await gatewayClient.deleteModelProvider(providerId));
      setSaveNotice(`已删除 Provider：${providerId}`);
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : "Provider 删除失败");
    } finally {
      setModelSaving(false);
    }
  }, [applyProviderCatalog, modelSaving]);

  useEffect(() => {
    void refreshContext();
  }, [refreshContext]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void gatewayClient.getHostContext().then(setContext).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!isRunning) {
      setPermission(null);
      return;
    }
    let active = true;
    const poll = () => {
      const conversationId = activeConversationIdRef.current;
      void Promise.all([
        gatewayClient.pendingPermissions(conversationId),
        gatewayClient.activity(conversationId),
      ])
        .then(([permissions, nextActivity]) => {
          if (active) {
            setPermission(permissions[0] ?? null);
            setActivity((current) => [
              ...current.filter((item) => ["step", "retry", "patch"].includes(item.tool)),
              ...nextActivity,
            ].slice(-20));
          }
        })
        .catch(() => undefined);
    };
    poll();
    const timer = window.setInterval(poll, 500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [isRunning]);

  useEffect(() => {
    const receiveHostContext = (event: MessageEvent<HostContextMessage>) => {
      if (event.source !== window.parent || event.origin !== parentOrigin) return;
      if (event.data?.type !== "geely-ai.host-context") return;
      if (event.data.host_session_id !== hostSessionId) return;
      void gatewayClient
        .updateHostContext(event.data.context)
        .then(setContext)
        .catch(reportError);
    };
    window.addEventListener("message", receiveHostContext);
    if (window.parent !== window) {
      window.parent.postMessage(
        { type: "geely-ai.copilot-ready", host_session_id: hostSessionId },
        parentOrigin,
      );
    }
    return () => window.removeEventListener("message", receiveHostContext);
  }, [reportError]);

  const run = useCallback(
    async (
      message: ChatMessage,
      action: (conversationId: string, signal: AbortSignal) => Promise<string | null>,
    ) => {
      if (isRunning) return;
      const conversationId = activeConversationIdRef.current;
      const controller = new AbortController();
      abortControllerRef.current = controller;
      appendMessage(conversationId, message);
      setActivity([]);
      setReasoning("");
      setTodos([]);
      setDiffResult(emptyDiffResult);
      setDiagnostic(null);
      setSaveNotice(null);
      setTurnStatus("running");
      try {
        const content = await action(conversationId, controller.signal);
        if (content) appendAssistant(conversationId, content);
        setActivity((current) => current.map((item) =>
          isActiveStatus(item.status) ? { ...item, status: "completed" } : item
        ));
        setTodos((current) => current.map((item) =>
          isActiveStatus(item.status) ? { ...item, status: "completed" } : item
        ));
        setTurnStatus("completed");
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          setActivity((current) => current.map((item) =>
            isActiveStatus(item.status) ? { ...item, status: "cancelled" } : item
          ));
          setTodos((current) => current.map((item) =>
            isActiveStatus(item.status) ? { ...item, status: "cancelled" } : item
          ));
          appendAssistant(conversationId, "已停止本次请求。");
          setTurnStatus("cancelled");
        } else {
          setActivity((current) => current.map((item) =>
            isActiveStatus(item.status) ? { ...item, status: "failed" } : item
          ));
          setTodos((current) => current.map((item) =>
            isActiveStatus(item.status) ? { ...item, status: "failed" } : item
          ));
          reportError(error, conversationId);
          setTurnStatus("failed");
        }
      } finally {
        if (abortControllerRef.current === controller) abortControllerRef.current = null;
      }
    },
    [appendAssistant, appendMessage, isRunning, reportError],
  );

  const askCopilot = useCallback(
    (
      question: string,
      attachments: CopilotAttachment[],
      history: CopilotHistoryMessage[],
      task: "chat" | "generate_test",
      displayAttachments?: readonly CompleteAttachment[],
    ) =>
      run(userMessage(question, displayAttachments), async (conversationId, signal) => {
        if (task === "chat") {
          const response = assistantMessage("");
          let answer = "";
          let added = false;
          await gatewayClient.streamCopilot(
            question,
            conversationId,
            attachments,
            history,
            (event) => {
              if (event.type === "text_delta") {
                answer += event.delta;
                if (!added) {
                  appendMessage(conversationId, response);
                  added = true;
                }
                updateMessage(conversationId, response.id, answer);
              } else if (event.type === "reasoning_delta") {
                if (!added) {
                  appendMessage(conversationId, response);
                  added = true;
                }
                setReasoning((current) => current + event.delta);
              } else if (event.type === "tool") {
                if (!added) {
                  appendMessage(conversationId, response);
                  added = true;
                }
                setActivity((current) => [
                  ...current.filter((item) => item.id !== event.id),
                  event,
                ].slice(-20));
              } else if (event.type === "step") {
                if (!added) {
                  appendMessage(conversationId, response);
                  added = true;
                }
                setActivity((current) => [
                  ...current.filter((item) => item.id !== event.id),
                  { ...event, tool: "step", output: "" },
                ].slice(-20));
              } else if (event.type === "todo") {
                if (!added) {
                  appendMessage(conversationId, response);
                  added = true;
                }
                setTodos(event.todos);
              } else if (event.type === "retry") {
                if (!added) {
                  appendMessage(conversationId, response);
                  added = true;
                }
                setActivity((current) => [
                  ...current.map((item) =>
                    item.tool === "retry" && isActiveStatus(item.status)
                      ? { ...item, status: "completed" }
                      : item
                  ).filter((item) => item.id !== `retry-${event.attempt}`),
                  {
                    id: `retry-${event.attempt}`,
                    tool: "retry",
                    status: "running",
                    title: event.message,
                    output: "",
                  },
                ].slice(-20));
              } else if (event.type === "patch") {
                if (!added) {
                  appendMessage(conversationId, response);
                  added = true;
                }
                setActivity((current) => [
                  ...current.filter((item) => item.id !== "workspace-patch"),
                  {
                    id: "workspace-patch",
                    tool: "patch",
                    status: "completed",
                    title: event.files.length ? `${event.files.length} 个文件发生变化` : "已记录文件变化",
                    output: event.files.join("\n"),
                  },
                ].slice(-20));
              } else if (event.type === "permission") {
                setPermission(event.permission);
              } else if (event.type === "error") {
                throw new GatewayRequestError(event.message, undefined, event.code ?? "agent_failed");
              }
            },
            signal,
          );
          if (!answer.trim()) throw new Error("CoreTest Agent returned an empty response");
          setDiffResult(await gatewayClient.diff(conversationId).catch(() => emptyDiffResult));
          return null;
        }
        const payload = await gatewayClient.queryCopilot(
          question,
          conversationId,
          attachments,
          history,
          task,
          signal,
        );
        if (payload.artifacts.length) {
          setConversations((current) => current.map((conversation) =>
            conversation.id === conversationId
              ? { ...conversation, artifacts: payload.artifacts, updatedAt: Date.now() }
              : conversation
          ));
        }
        setDiffResult(await gatewayClient.diff(conversationId).catch(() => emptyDiffResult));
        return formatCopilotResponse(payload);
      }),
    [appendMessage, run, updateMessage],
  );

  const suggestions = useMemo(() => {
    if (composerAttachmentCount) {
      return [
        { prompt: "概括已添加文件" },
        { prompt: "查找潜在异常" },
      ];
    }
    if (hasCurrentData) {
      return [
        { prompt: "概括当前对象" },
        { prompt: "查找异常" },
      ];
    }
    return [];
  }, [composerAttachmentCount, hasCurrentData]);

  const runtime = useExternalStoreRuntime<ChatMessage>({
    messages,
    isRunning,
    convertMessage,
    adapters: { attachments: attachmentAdapter },
    onNew: async (message) => {
      const question = messageText(message);
      if (!question) return;
      const task = message.runConfig?.custom?.task === "generate_test" ? "generate_test" : "chat";
      try {
        await askCopilot(
          question,
          await messageAttachments(message),
          conversationHistory(messages),
          task,
          message.attachments,
        );
      } catch (error) {
        const conversationId = activeConversationIdRef.current;
        appendMessage(conversationId, userMessage(question, message.attachments));
        reportError(error, conversationId);
      }
    },
    onCancel: async () => {
      abortControllerRef.current?.abort();
      await gatewayClient.abortConversation(activeConversationIdRef.current).catch(() => undefined);
    },
    suggestions,
  });

  useEffect(() => {
    const updateCount = () => {
      setComposerAttachmentCount(runtime.thread.composer.getState().attachments.length);
    };
    updateCount();
    return runtime.thread.composer.subscribe(updateCount);
  }, [runtime]);

  const composerConversationRef = useRef(activeConversationId);
  useEffect(() => {
    if (composerConversationRef.current === activeConversationId) return;
    composerConversationRef.current = activeConversationId;
    setComposerAttachmentCount(0);
    setActivity([]);
    setReasoning("");
    setTodos([]);
    setDiffResult(emptyDiffResult);
    setTurnStatus("idle");
    void runtime.thread.composer.reset();
  }, [activeConversationId, runtime]);

  const generateTests = useCallback(() => {
    const composer = runtime.thread.composer;
    if (composer.getState().attachments.length) {
      composer.setText(
        "先理解当前工程和已添加文件，在工程合适的测试目录创建或修改 pytest 测试，"
        + "然后自动运行最小相关测试并根据结果修正。不要修改 CoreTest 或 CoreTest Agent 产品源码。",
      );
      composer.setRunConfig({ custom: { task: "chat" } });
      composer.send();
      return;
    }
    if (hasSelectedFile) {
      void askCopilot(
        "先理解当前工程和选中的文件，在工程合适的测试目录创建或修改 pytest 测试，"
          + "然后自动运行最小相关测试并根据结果修正。不要修改 CoreTest 或 CoreTest Agent 产品源码。",
        [],
        conversationHistory(messages),
        "chat",
      );
    }
  }, [askCopilot, hasSelectedFile, messages, runtime]);

  const replyPermission = useCallback(async (reply: "once" | "reject") => {
    if (!permission || permissionReplying) return;
    setPermissionReplying(true);
    try {
      await gatewayClient.replyPermission(
        activeConversationIdRef.current,
        permission.id,
        reply,
      );
      setPermission(null);
    } catch (error) {
      reportError(error);
    } finally {
      setPermissionReplying(false);
    }
  }, [permission, permissionReplying, reportError]);

  const revertLatestTurn = useCallback(async () => {
    if (reverting || !diffResult.revert_available) return;
    if (!window.confirm("确认撤销本轮智能体产生的全部文件修改？")) return;
    setReverting(true);
    try {
      const reverted = await gatewayClient.revert(activeConversationIdRef.current);
      if (!reverted) throw new Error("当前没有可撤销的智能体修改。");
      setDiffResult(emptyDiffResult);
      setSaveNotice("已撤销本轮智能体修改");
    } catch (error) {
      reportError(error);
    } finally {
      setReverting(false);
    }
  }, [diffResult.revert_available, reportError, reverting]);

  const startNewConversation = useCallback(async () => {
    if (isRunning) return;
    await runtime.thread.composer.reset();
    setComposerAttachmentCount(0);
    setDiagnostic(null);
    setSaveNotice(null);
    if (
      activeConversation?.projectKey === currentProjectKey
      && activeConversation.messages.length === 0
      && activeConversation.artifacts.length === 0
    ) {
      setHistoryOpen(false);
      return;
    }
    const conversation = createConversation(currentProjectKey);
    setConversations((current) => [...current, conversation]);
    setActiveConversationId(conversation.id);
    setHistoryOpen(false);
  }, [activeConversation, currentProjectKey, isRunning, runtime]);

  const selectConversation = useCallback((conversationId: string) => {
    if (isRunning) return;
    setActiveConversationId(conversationId);
    setHistoryOpen(false);
  }, [isRunning]);

  const projectConversations = useMemo(
    () => conversations
      .filter((conversation) => conversation.projectKey === currentProjectKey)
      .sort((left, right) => right.updatedAt - left.updatedAt),
    [conversations, currentProjectKey],
  );

  const downloadArtifact = useCallback((artifact: CopilotArtifact) => {
    const url = URL.createObjectURL(new Blob([artifact.content], { type: "text/x-python" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = artifact.name;
    link.click();
    URL.revokeObjectURL(url);
    setSaveNotice(`已提交保存请求：${artifact.name}`);
  }, []);

  const copyArtifact = useCallback(async (artifact: CopilotArtifact) => {
    try {
      await navigator.clipboard.writeText(artifact.content);
      setSaveNotice(`已复制：${artifact.name}`);
    } catch (error) {
      reportError(error);
    }
  }, [reportError]);

  const contextLabel = context.selection_label || context.current_view || "等待选择";

  return (
    <FluentProvider theme={agentLightTheme} className="app-provider">
      <main className="copilot-shell">
        <OverlayDrawer
          className="history-drawer"
          open={historyOpen}
          position="start"
          onOpenChange={(_, data) => setHistoryOpen(data.open)}
        >
          <DrawerHeader>
            <DrawerHeaderTitle
              action={
                <Button
                  appearance="subtle"
                  icon={<Dismiss24Regular />}
                  aria-label="关闭历史对话"
                  title="关闭"
                  onClick={() => setHistoryOpen(false)}
                />
              }
            >
              历史对话
            </DrawerHeaderTitle>
          </DrawerHeader>
          <DrawerBody>
            <Button
              className="history-new-button"
              appearance="primary"
              icon={<Add20Regular />}
              onClick={() => void startNewConversation()}
              disabled={isRunning}
            >
              新建对话
            </Button>
            <div className="history-list" aria-label="当前工程的历史对话">
              {projectConversations.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className="history-item"
                  aria-current={conversation.id === activeConversationId ? "true" : undefined}
                  onClick={() => selectConversation(conversation.id)}
                  disabled={isRunning}
                >
                  <span className="history-item-title">{conversation.title}</span>
                  <span className="history-item-meta">
                    {updatedTime(conversation.updatedAt)} · {conversation.messages.length} 条消息
                  </span>
                </button>
              ))}
            </div>
            <p className="history-note">历史仅保存在本机当前用户配置中</p>
          </DrawerBody>
        </OverlayDrawer>

        <OverlayDrawer
          className="settings-drawer"
          open={settingsOpen}
          position="end"
          onOpenChange={(_, data) => setSettingsOpen(data.open)}
        >
          <DrawerHeader>
            <DrawerHeaderTitle
              action={
                <Button
                  appearance="subtle"
                  icon={<Dismiss24Regular />}
                  aria-label="关闭模型设置"
                  title="关闭"
                  onClick={() => setSettingsOpen(false)}
                />
              }
            >
              模型与 API
            </DrawerHeaderTitle>
          </DrawerHeader>
          <DrawerBody>
            <div className="provider-settings">
              <section className="provider-section" aria-labelledby="provider-list-title">
                <div className="provider-section-heading">
                  <h3 id="provider-list-title">已配置</h3>
                  <span>{modelProviders?.providers.length ?? 0}</span>
                </div>
                <div className="provider-list">
                  {(modelProviders?.providers ?? []).map((provider) => {
                    const selectedModel = providerModels[provider.id] ?? provider.models[0]?.id ?? "";
                    const isActive = provider.id === modelProviders?.active_provider_id
                      && selectedModel === modelProviders.active_model_id;
                    return (
                      <article className="provider-item" key={provider.id}>
                        <div className="provider-item-heading">
                          <div>
                            <strong>{provider.name}</strong>
                            <span>{provider.id}</span>
                          </div>
                          <span className={provider.api_key_configured ? "provider-status ready" : "provider-status"}>
                            {provider.api_key_configured ? "已连接" : "缺少 Key"}
                          </span>
                        </div>
                        <span className="provider-url" title={provider.base_url}>{provider.base_url}</span>
                        <label className="provider-model-select">
                          <span>模型</span>
                          <select
                            value={selectedModel}
                            onChange={(event) => setProviderModels((current) => ({
                              ...current,
                              [provider.id]: event.target.value,
                            }))}
                            disabled={modelSaving || isRunning}
                          >
                            {provider.models.map((model) => (
                              <option key={model.id} value={model.id}>{model.name}</option>
                            ))}
                          </select>
                        </label>
                        <div className="provider-actions">
                          <Button
                            appearance={isActive ? "secondary" : "primary"}
                            icon={<CheckmarkCircle20Regular />}
                            disabled={isActive || modelSaving || isRunning || !selectedModel}
                            onClick={() => void selectModel(provider.id, selectedModel)}
                          >
                            {isActive ? "使用中" : "使用"}
                          </Button>
                          <Button
                            appearance="subtle"
                            icon={testingProviderId === provider.id ? <Spinner size="tiny" /> : <Play20Regular />}
                            disabled={modelSaving || isRunning || !selectedModel || !provider.api_key_configured}
                            onClick={() => void testProvider(provider.id)}
                          >
                            {testingProviderId === provider.id ? "测试中…" : "测试"}
                          </Button>
                          <Button
                            appearance="subtle"
                            icon={<Delete20Regular />}
                            disabled={modelSaving || isRunning}
                            onClick={() => void deleteProvider(provider.id)}
                          >
                            删除
                          </Button>
                        </div>
                      </article>
                    );
                  })}
                  {modelProviders && !modelProviders.providers.length && (
                    <p className="provider-empty">尚未配置模型 API</p>
                  )}
                </div>
              </section>

              {settingsError && <p className="settings-error" role="alert">{settingsError}</p>}

              <section className="provider-section provider-create" aria-labelledby="provider-create-title">
                <div className="provider-section-heading">
                  <h3 id="provider-create-title">添加 Provider</h3>
                </div>
                <div className="settings-form">
                  <Field label="Provider ID" hint="字母、数字、下划线或连字符">
                    <Input
                      value={providerIdDraft}
                      onChange={(_, data) => setProviderIdDraft(data.value)}
                      placeholder="company-api"
                    />
                  </Field>
                  <Field label="显示名称">
                    <Input
                      value={providerNameDraft}
                      onChange={(_, data) => setProviderNameDraft(data.value)}
                      placeholder="Company API"
                    />
                  </Field>
                  <Field label="API Base URL">
                    <Input
                      value={providerUrlDraft}
                      onChange={(_, data) => setProviderUrlDraft(data.value)}
                      placeholder="https://api.example.com/v1"
                    />
                  </Field>
                  <Field label="API Key" hint="保存到本机 Agent 凭据，不会回显">
                    <Input
                      type="password"
                      value={providerKeyDraft}
                      onChange={(_, data) => setProviderKeyDraft(data.value)}
                      placeholder="输入 API Key"
                    />
                  </Field>
                  <Field label="模型" hint="每行一个：模型 ID | 显示名称">
                    <Textarea
                      value={providerModelsDraft}
                      onChange={(_, data) => setProviderModelsDraft(data.value)}
                      placeholder={"gpt-5.5 | GPT 5.5\ngpt-5-mini | GPT 5 mini"}
                      resize="vertical"
                    />
                  </Field>
                  <Button
                    appearance="primary"
                    icon={<Add20Regular />}
                    onClick={() => void saveProvider()}
                    disabled={
                      isRunning
                      || modelSaving
                      || !providerIdDraft.trim()
                      || !providerNameDraft.trim()
                      || !providerUrlDraft.trim()
                      || !providerKeyDraft.trim()
                      || !providerModelsDraft.trim()
                    }
                  >
                    {modelSaving ? "处理中…" : "保存并使用"}
                  </Button>
                </div>
              </section>
            </div>
          </DrawerBody>
        </OverlayDrawer>

        <section className="chat-region" aria-label="CoreTest Agent 对话">
          <AssistantRuntimeProvider runtime={runtime}>
            <AgentThread
              hostConnected={hostConnected}
              contextLabel={contextLabel}
              dataLabel={dataLabel}
              suggestions={suggestions}
              turnStatus={turnStatus}
              lastMessageRole={lastMessageRole}
              latestAssistantId={latestAssistantId}
              activity={activity}
              reasoning={reasoning}
              todos={todos}
              permission={permission}
              permissionReplying={permissionReplying}
              onReplyPermission={(reply) => void replyPermission(reply)}
              diffResult={diffResult}
              reverting={reverting}
              onRevert={() => void revertLatestTurn()}
              artifacts={artifacts}
              onCopyArtifact={(artifact) => void copyArtifact(artifact)}
              onDownloadArtifact={downloadArtifact}
              diagnostic={diagnostic}
              saveNotice={saveNotice}
              composerAttachmentCount={composerAttachmentCount}
              onGenerateTests={generateTests}
              modelProviders={modelProviders}
              modelSaving={modelSaving}
              onSelectModel={(providerId, modelId) => void selectModel(providerId, modelId)}
              historyCount={projectConversations.length}
              onOpenHistory={() => setHistoryOpen(true)}
              onOpenSettings={openSettings}
            />
          </AssistantRuntimeProvider>
        </section>
      </main>
    </FluentProvider>
  );
}

function resolveParentOrigin(): string {
  const configuredOrigin = new URLSearchParams(window.location.search).get("host_origin");
  if (!configuredOrigin) return window.location.origin;
  try {
    const origin = new URL(configuredOrigin).origin;
    return origin === "null" ? window.location.origin : origin;
  } catch {
    return window.location.origin;
  }
}
