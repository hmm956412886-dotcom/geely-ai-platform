import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  SimpleTextAttachmentAdapter,
  useExternalStoreRuntime,
  type AppendMessage,
  type CompleteAttachment,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { makeMarkdownText, Thread } from "@assistant-ui/react-ui";
import {
  Button,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  FluentProvider,
  OverlayDrawer,
  Spinner,
  webLightTheme,
} from "@fluentui/react-components";
import {
  Add20Regular,
  ArrowDownload20Regular,
  ArrowSync20Regular,
  CheckmarkCircle20Regular,
  Code20Regular,
  ChevronRight16Regular,
  Copy20Regular,
  Dismiss24Regular,
  DocumentData20Regular,
  History20Regular,
  ShieldLock20Regular,
} from "@fluentui/react-icons";
import { GatewayRequestError, gatewayClient, hostSessionId } from "./gatewayClient";
import type {
  AgentActivity,
  AgentFileDiff,
  AgentPermission,
  CopilotArtifact,
  CopilotAttachment,
  CopilotHistoryMessage,
  CopilotResponse,
  HostContext,
  HostContextMessage,
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

const parentOrigin = resolveParentOrigin();
const MarkdownText = makeMarkdownText();
const attachmentAccept = [
  ".py", ".json", ".yaml", ".yml", ".xml", ".txt", ".dbc", ".md",
  ".toml", ".ini", ".cfg", ".csv", ".log", ".asc",
].join(",");
const maxAttachments = 5;
const maxFileBytes = 256 * 1024;
const maxTotalBytes = 512 * 1024;

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
  return `### AI 说明\n\n${payload.answer}${generated}${formatReferences(payload)}`;
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
  if (error instanceof TypeError && error.message.includes("fetch")) {
    return "无法连接 AI Gateway，请确认服务已启动。";
  }
  if (error instanceof GatewayRequestError) return "请求未能完成，请检查输入后重试。";
  return error instanceof Error ? error.message : "请求未能完成，请稍后重试。";
}

export default function App() {
  const [context, setContext] = useState<HostContext>(emptyContext);
  const [conversations, setConversations] = useState<Conversation[]>(() => [
    createConversation(projectKey(emptyContext)),
  ]);
  const [activeConversationId, setActiveConversationId] = useState(() =>
    conversations[0].id
  );
  const [historyOpen, setHistoryOpen] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [contextLoading, setContextLoading] = useState(true);
  const [contextExpanded, setContextExpanded] = useState(false);
  const [composerAttachmentCount, setComposerAttachmentCount] = useState(0);
  const [diagnostic, setDiagnostic] = useState<RequestDiagnostic | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [permission, setPermission] = useState<AgentPermission | null>(null);
  const [permissionReplying, setPermissionReplying] = useState(false);
  const [activity, setActivity] = useState<AgentActivity[]>([]);
  const [fileDiffs, setFileDiffs] = useState<AgentFileDiff[]>([]);
  const [reverting, setReverting] = useState(false);
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
        `### 请求未完成\n\n${localizedError(error)}`,
      );
    },
    [appendAssistant],
  );

  const refreshContext = useCallback(async () => {
    setContextLoading(true);
    try {
      setContext(await gatewayClient.getHostContext());
    } catch (error) {
      reportError(error);
    } finally {
      setContextLoading(false);
    }
  }, [reportError]);

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
            setActivity(nextActivity);
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
      setFileDiffs([]);
      setDiagnostic(null);
      setSaveNotice(null);
      setIsRunning(true);
      try {
        const content = await action(conversationId, controller.signal);
        if (content) appendAssistant(conversationId, content);
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          appendAssistant(conversationId, "已停止本次请求。");
        } else {
          reportError(error, conversationId);
        }
      } finally {
        if (abortControllerRef.current === controller) abortControllerRef.current = null;
        setIsRunning(false);
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
                updateMessage(conversationId, response.id, `### AI 说明\n\n${answer}`);
              } else if (event.type === "tool") {
                setActivity((current) => [
                  ...current.filter((item) => item.id !== event.id),
                  event,
                ].slice(-20));
              } else if (event.type === "permission") {
                setPermission(event.permission);
              } else if (event.type === "error") {
                throw new GatewayRequestError(event.message, undefined, "model_unavailable");
              }
            },
            signal,
          );
          if (!answer.trim()) throw new Error("OpenCode returned an empty response");
          setFileDiffs(await gatewayClient.diff(conversationId).catch(() => []));
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
        setFileDiffs(await gatewayClient.diff(conversationId).catch(() => []));
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
    setFileDiffs([]);
    void runtime.thread.composer.reset();
  }, [activeConversationId, runtime]);

  const generateTests = useCallback(() => {
    const composer = runtime.thread.composer;
    if (composer.getState().attachments.length) {
      composer.setText("基于已添加文件生成可运行的 pytest 测试代码。");
      composer.setRunConfig({ custom: { task: "generate_test" } });
      composer.send();
      return;
    }
    if (hasSelectedFile) {
      void askCopilot(
        "基于当前选中的工程文件生成可运行的 pytest 测试代码。",
        [],
        conversationHistory(messages),
        "generate_test",
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
    if (reverting || !fileDiffs.length) return;
    if (!window.confirm("确认撤销本轮智能体产生的全部文件修改？")) return;
    setReverting(true);
    try {
      const reverted = await gatewayClient.revert(activeConversationIdRef.current);
      if (!reverted) throw new Error("当前没有可撤销的智能体修改。");
      setFileDiffs([]);
      setSaveNotice("已撤销本轮智能体修改");
    } catch (error) {
      reportError(error);
    } finally {
      setReverting(false);
    }
  }, [fileDiffs.length, reportError, reverting]);

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
  const projectLabel = context.project_label || (hostConnected ? "未打开工程" : "未连接 CoreTest");
  const connectionLabel = contextLoading ? "同步中" : hostConnected ? "已连接" : "未连接";

  return (
    <FluentProvider theme={webLightTheme} className="app-provider">
      <main className="copilot-shell">
        <header className="shell-header">
          <div className="title-block">
            <h1>CoreTest Copilot</h1>
            <p>{projectLabel}</p>
            <div className="header-status" aria-label="Copilot 状态">
              <span><ShieldLock20Regular aria-hidden="true" />操作需审批</span>
              <span className={hostConnected ? "is-connected" : "is-disconnected"}>
                {connectionLabel}
              </span>
            </div>
          </div>
          <div className="header-actions">
            <Button
              appearance="subtle"
              icon={<History20Regular />}
              aria-label="历史对话"
              title="历史对话"
              onClick={() => setHistoryOpen(true)}
              disabled={isRunning}
            />
            <Button
              appearance="subtle"
              icon={contextLoading ? <Spinner size="tiny" /> : <ArrowSync20Regular />}
              aria-label="刷新上下文"
              title="刷新上下文"
              onClick={() => void refreshContext()}
              disabled={contextLoading}
            />
            <Button
              appearance="subtle"
              icon={<Add20Regular />}
              aria-label="新建对话"
              title="新建对话"
              onClick={() => void startNewConversation()}
              disabled={isRunning}
            />
          </div>
        </header>

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
            <p className="history-note">历史仅保留在本次 CoreTest 运行期间</p>
          </DrawerBody>
        </OverlayDrawer>

        <button
          type="button"
          className="context-bar"
          aria-expanded={contextExpanded}
          onClick={() => setContextExpanded((current) => !current)}
          disabled={!hasCurrentData}
          title={contextLabel}
        >
          <DocumentData20Regular aria-hidden="true" />
          <span><strong>{dataLabel}</strong>{contextLabel}</span>
          {hasCurrentData && (
            <ChevronRight16Regular className={contextExpanded ? "is-expanded" : ""} aria-hidden="true" />
          )}
        </button>

        {contextExpanded && hasCurrentData && (
          <section className="context-details" aria-label="当前上下文详情">
            <dl>
              <div><dt>来源</dt><dd>{dataLabel}</dd></div>
              <div><dt>对象</dt><dd title={contextLabel}>{contextLabel}</dd></div>
              <div><dt>版本</dt><dd>{context.snapshot_revision}</dd></div>
            </dl>
            <div className="context-actions">
              <Button
                size="small"
                appearance="subtle"
                onClick={() => void askCopilot(
                  `概括当前 ${dataLabel} 的关键信息。`, [], conversationHistory(messages), "chat"
                )}
                disabled={isRunning}
              >
                概括
              </Button>
              <Button
                size="small"
                appearance="subtle"
                onClick={() => void askCopilot(
                  `检查当前 ${dataLabel} 的异常和风险。`, [], conversationHistory(messages), "chat"
                )}
                disabled={isRunning}
              >
                查异常
              </Button>
              {hasSelectedFile && (
                <Button
                  size="small"
                  appearance="subtle"
                  icon={<Code20Regular />}
                  onClick={generateTests}
                  disabled={isRunning}
                >
                  生成 pytest
                </Button>
              )}
            </div>
          </section>
        )}

        {composerAttachmentCount > 0 && (
          <div className="attachment-actions">
            <span>已添加 {composerAttachmentCount} 个文件</span>
            <Button
              appearance="subtle"
              icon={<Code20Regular />}
              onClick={generateTests}
              disabled={isRunning}
            >
              生成 pytest
            </Button>
          </div>
        )}

        <section className="chat-region" aria-label="Copilot 对话">
          <AssistantRuntimeProvider runtime={runtime}>
            <Thread
              welcome={{
                message: hasCurrentData
                  ? `已同步：${contextLabel}`
                  : hostConnected ? "请选择工程对象，或直接提问" : "等待 CoreTest 连接",
                suggestions,
              }}
              assistantAvatar={{ fallback: "AI" }}
              userMessage={{ allowEdit: false }}
              assistantMessage={{
                allowReload: false,
                allowCopy: true,
                allowSpeak: false,
                allowFeedbackPositive: false,
                allowFeedbackNegative: false,
                components: { Text: MarkdownText },
              }}
              composer={{ allowAttachments: true }}
              strings={{
                thread: { scrollToBottom: { tooltip: "滚动到底部" } },
                composer: {
                  input: {
                    placeholder: hostConnected
                      ? "询问当前内容..."
                      : "输入问题...",
                  },
                  addAttachment: { tooltip: "添加参考文件" },
                  send: { tooltip: "发送" },
                  cancel: { tooltip: "停止" },
                  removeAttachment: { tooltip: "移除附件" },
                },
                assistantMessage: { copy: { tooltip: "复制" } },
              }}
            />
          </AssistantRuntimeProvider>
        </section>

        {activity.length > 0 && (
          <section className="activity-panel" aria-label="智能体执行步骤">
            <div className="activity-title">
              <Code20Regular aria-hidden="true" />
              <strong>执行步骤</strong>
              <span>{activity.length}</span>
            </div>
            <div className="activity-list">
              {activity.map((step) => (
                <div className="activity-item" key={step.id}>
                  {step.status === "running" || step.status === "pending"
                    ? <Spinner size="extra-tiny" />
                    : <CheckmarkCircle20Regular aria-hidden="true" />}
                  <div>
                    <strong>{toolLabel(step.tool)}</strong>
                    <code title={step.title}>{step.title}</code>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {fileDiffs.length > 0 && (
          <section className="diff-panel" aria-label="本轮文件变更">
            <div className="diff-heading">
              <div>
                <strong>文件变更</strong>
                <span>{fileDiffs.length} 个文件 · 仅本轮智能体修改</span>
              </div>
              <Button
                size="small"
                appearance="subtle"
                onClick={() => void revertLatestTurn()}
                disabled={reverting || isRunning}
              >
                {reverting ? "撤销中…" : "撤销本轮"}
              </Button>
            </div>
            <div className="diff-files">
              {fileDiffs.map((file) => (
                <details key={file.path}>
                  <summary>
                    <ChevronRight16Regular className="diff-chevron" aria-hidden="true" />
                    <code title={file.path}>{file.path}</code>
                    <span className="diff-additions">+{file.additions}</span>
                    <span className="diff-deletions">−{file.deletions}</span>
                  </summary>
                  <pre>{file.patch || "未返回文本补丁"}</pre>
                  {file.truncated && <small>补丁过长，已截断显示</small>}
                </details>
              ))}
            </div>
          </section>
        )}

        {permission && (
          <section className="permission-panel" role="alert" aria-label="智能体操作审批">
            <div className="permission-heading">
              <ShieldLock20Regular aria-hidden="true" />
              <div>
                <strong>{permissionLabel(permission.permission)}</strong>
                <span>OpenCode 请求执行以下操作</span>
              </div>
            </div>
            {permission.resources.length > 0 && (
              <div className="permission-resources">
                {permission.resources.map((resource) => <code key={resource}>{resource}</code>)}
              </div>
            )}
            <div className="permission-actions">
              <Button
                appearance="secondary"
                onClick={() => void replyPermission("reject")}
                disabled={permissionReplying}
              >
                拒绝
              </Button>
              <Button
                appearance="primary"
                onClick={() => void replyPermission("once")}
                disabled={permissionReplying}
              >
                允许一次
              </Button>
            </div>
          </section>
        )}

        {(diagnostic || saveNotice) && (
          <div className="status-strip" role="status">
            {saveNotice && (
              <span className="save-notice">
                <CheckmarkCircle20Regular aria-hidden="true" />
                <span>{saveNotice}</span>
              </span>
            )}
            {diagnostic && (
              <details className="diagnostic-details">
                <summary>诊断详情</summary>
                <p>{diagnostic.detail}</p>
                {diagnostic.requestId && (
                  <div className="request-id-row">
                    <code title={diagnostic.requestId}>{diagnostic.requestId}</code>
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<Copy20Regular />}
                      aria-label="复制 request ID"
                      title="复制 request ID"
                      onClick={() => void navigator.clipboard.writeText(diagnostic.requestId || "")}
                    />
                  </div>
                )}
              </details>
            )}
          </div>
        )}

        {artifacts.length > 0 && (
          <div className="artifact-actions" aria-label="生成结果">
            {artifacts.map((artifact) => (
              <div className="artifact-item" key={artifact.name}>
                <span><Code20Regular aria-hidden="true" />{artifact.name}</span>
                <div>
                  <Button
                    appearance="subtle"
                    icon={<Copy20Regular />}
                    aria-label={`复制 ${artifact.name}`}
                    title="复制代码"
                    onClick={() => void copyArtifact(artifact)}
                  />
                  <Button
                    appearance="primary"
                    icon={<ArrowDownload20Regular />}
                    aria-label={`保存 ${artifact.name}`}
                    title="保存到 generated_tests"
                    onClick={() => downloadArtifact(artifact)}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </FluentProvider>
  );
}

function permissionLabel(permission: string): string {
  const labels: Record<string, string> = {
    bash: "运行命令",
    edit: "修改工作区文件",
    write: "写入工作区文件",
    apply_patch: "应用代码修改",
  };
  return labels[permission] ?? "执行工具操作";
}

function toolLabel(tool: string): string {
  const labels: Record<string, string> = {
    glob: "搜索文件",
    grep: "搜索代码",
    read: "读取文件",
    lsp: "分析代码",
    edit: "修改文件",
    bash: "运行命令",
  };
  return labels[tool] ?? tool;
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
