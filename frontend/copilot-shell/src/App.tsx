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
  Code20Regular,
  ChevronRight16Regular,
  Dismiss24Regular,
  DocumentData20Regular,
  History20Regular,
} from "@fluentui/react-icons";
import { GatewayRequestError, gatewayClient, hostSessionId } from "./gatewayClient";
import type {
  AnalysisResponse,
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

const parentOrigin = resolveParentOrigin();
const MarkdownText = makeMarkdownText();
const attachmentAccept = [
  ".py", ".json", ".yaml", ".yml", ".xml", ".txt", ".dbc", ".md",
  ".toml", ".ini", ".cfg", ".csv", ".log", ".asc",
].join(",");

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
  return Promise.all(
    items.map(async (attachment) => {
      if (!attachment.file) throw new Error(`无法读取附件 ${attachment.name}`);
      return {
        name: attachment.name,
        content: await attachment.file.text(),
        size: attachment.file.size,
      };
    }),
  );
}

function conversationHistory(messages: ChatMessage[]): CopilotHistoryMessage[] {
  return messages.slice(-20).map(({ role, content }) => ({ role, content }));
}

function formatResponse(payload: AnalysisResponse): string {
  const citation = payload.citations[0];
  const source = citation
    ? `\n\n**参考**：[${citation.title}](${citation.source_url}) · ${citation.provider}`
    : "";
  const warning = payload.warnings.length ? `\n\n> ${payload.warnings.join("；")}` : "";
  return `${payload.answer}${source}${warning}`;
}

function formatCopilotResponse(payload: CopilotResponse): string {
  const generated = payload.artifacts
    .map((artifact) => `\n\n### ${artifact.name}\n\n\`\`\`${artifact.language}\n${artifact.content}\`\`\``)
    .join("");
  return `${payload.answer}${generated}`;
}

function currentDataLabel(context: HostContext): string {
  const labels: Record<string, string> = {
    trace: "Trace",
    dbc: "DBC",
    diagnostic: "诊断数据",
    project: "当前工程",
    pdx: "PDX",
  };
  return labels[context.selection_kind ?? ""] ?? "当前内容";
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
  const [composerAttachmentCount, setComposerAttachmentCount] = useState(0);
  const activeConversationIdRef = useRef(activeConversationId);
  const currentProjectKey = projectKey(context);
  const activeConversation = conversations.find(({ id }) => id === activeConversationId);
  const messages = activeConversation?.messages ?? [];
  const artifacts = activeConversation?.artifacts ?? [];
  const hostConnected = Boolean(context.host_application);
  const hasCurrentData = Boolean(context.selection_kind && context.snapshot_revision);
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

  const reportError = useCallback(
    (error: unknown, conversationId = activeConversationIdRef.current) => {
      const requestId = error instanceof GatewayRequestError ? error.requestId : undefined;
      const message = error instanceof Error ? error.message : "请求失败";
      appendAssistant(
        conversationId,
        `### 请求失败\n\n${message}${requestId ? `\n\n\`request_id: ${requestId}\`` : ""}`,
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
    async (message: ChatMessage, action: (conversationId: string) => Promise<string>) => {
      if (isRunning) return;
      const conversationId = activeConversationIdRef.current;
      appendMessage(conversationId, message);
      setIsRunning(true);
      try {
        appendAssistant(conversationId, await action(conversationId));
      } catch (error) {
        reportError(error, conversationId);
      } finally {
        setIsRunning(false);
      }
    },
    [appendAssistant, appendMessage, isRunning, reportError],
  );

  const analyze = useCallback(
    (question: string) =>
      run(
        userMessage(question),
        async () => formatResponse(await gatewayClient.analyzeSnapshot(question)),
      ),
    [run],
  );

  const askCopilot = useCallback(
    (
      question: string,
      attachments: CopilotAttachment[],
      history: CopilotHistoryMessage[],
      task: "chat" | "generate_test",
      displayAttachments?: readonly CompleteAttachment[],
    ) =>
      run(userMessage(question, displayAttachments), async (conversationId) => {
        const payload = await gatewayClient.queryCopilot(question, attachments, history, task);
        if (payload.artifacts.length) {
          setConversations((current) => current.map((conversation) =>
            conversation.id === conversationId
              ? { ...conversation, artifacts: payload.artifacts, updatedAt: Date.now() }
              : conversation
          ));
        }
        return formatCopilotResponse(payload);
      }),
    [run],
  );

  const suggestions = useMemo(() => {
    if (composerAttachmentCount) {
      return [
        { prompt: "分析已添加文件的主要逻辑和风险。" },
      ];
    }
    if (hasCurrentData) {
      return [{ prompt: `分析当前 ${dataLabel}，指出关键信息、异常和下一步建议。` }];
    }
    return [];
  }, [composerAttachmentCount, dataLabel, hasCurrentData]);

  const runtime = useExternalStoreRuntime<ChatMessage>({
    messages,
    isRunning,
    convertMessage,
    adapters: { attachments: attachmentAdapter },
    onNew: async (message) => {
      const question = messageText(message);
      if (!question) return;
      const task = message.runConfig?.custom?.task === "generate_test" ? "generate_test" : "chat";
      await askCopilot(
        question,
        await messageAttachments(message),
        conversationHistory(messages),
        task,
        message.attachments,
      );
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
    void runtime.thread.composer.reset();
  }, [activeConversationId, runtime]);

  const generateTests = useCallback(() => {
    const composer = runtime.thread.composer;
    if (!composer.getState().attachments.length) return;
    composer.setText("基于已添加文件生成可运行的 pytest 测试代码。");
    composer.setRunConfig({ custom: { task: "generate_test" } });
    composer.send();
  }, [runtime]);

  const startNewConversation = useCallback(async () => {
    if (isRunning) return;
    await runtime.thread.composer.reset();
    setComposerAttachmentCount(0);
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
  }, []);

  const contextLabel = context.selection_label || context.current_view || "等待选择";

  return (
    <FluentProvider theme={webLightTheme} className="app-provider">
      <main className="copilot-shell">
        <header className="shell-header">
          <div className="title-block">
            <h1>Copilot</h1>
            <p>{context.project_id || (hostConnected ? "未打开工程" : "未连接 CoreTest")}</p>
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
          onClick={() => hasCurrentData && void analyze(`概括当前 ${dataLabel} 的关键信息。`)}
          disabled={!hasCurrentData || isRunning}
          title={contextLabel}
        >
          <DocumentData20Regular aria-hidden="true" />
          <span>{contextLabel}</span>
          {hasCurrentData && <ChevronRight16Regular aria-hidden="true" />}
        </button>

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
                message: hostConnected ? "需要分析什么？" : "连接 CoreTest 后开始",
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
                      ? "询问当前内容或添加文件..."
                      : "输入问题或添加文件...",
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

        {artifacts.length > 0 && (
          <div className="artifact-actions" aria-label="生成结果">
            {artifacts.map((artifact) => (
              <Button
                key={artifact.name}
                appearance="secondary"
                icon={<ArrowDownload20Regular />}
                onClick={() => downloadArtifact(artifact)}
              >
                保存 {artifact.name}
              </Button>
            ))}
          </div>
        )}
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
