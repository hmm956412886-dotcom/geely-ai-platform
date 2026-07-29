import { useCallback, useEffect, useMemo, useState } from "react";
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
  Badge,
  Button,
  FluentProvider,
  Spinner,
  Tooltip,
  webLightTheme,
} from "@fluentui/react-components";
import {
  ArrowDownload20Regular,
  ArrowSync20Regular,
  ChartMultiple20Regular,
  Code20Regular,
  ShieldCheckmark20Regular,
  Sparkle20Filled,
} from "@fluentui/react-icons";
import { GatewayRequestError, gatewayClient, hostSessionId } from "./gatewayClient";
import type {
  AnalysisResponse,
  CopilotArtifact,
  CopilotAttachment,
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

const initialMessages: ChatMessage[] = [
  {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "你好，我是 CoreTest Copilot。",
  },
];

function assistantMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "assistant", content };
}

function userMessage(
  content: string,
  attachments?: readonly CompleteAttachment[],
): ChatMessage {
  return { id: crypto.randomUUID(), role: "user", content, attachments };
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

function formatResponse(payload: AnalysisResponse): string {
  const citation = payload.citations[0];
  const source = citation
    ? `\n\n**参考**：[${citation.title}](${citation.source_url}) · ${citation.provider}`
    : "";
  const warning = payload.warnings.length ? `\n\n> ${payload.warnings.join("；")}` : "";
  return `${payload.answer}${source}${warning}\n\n\`request_id: ${payload.request_id}\``;
}

function formatCopilotResponse(payload: CopilotResponse): string {
  const generated = payload.artifacts
    .map((artifact) => `\n\n### ${artifact.name}\n\n\`\`\`${artifact.language}\n${artifact.content}\`\`\``)
    .join("");
  return `${payload.answer}${generated}\n\n\`request_id: ${payload.request_id}\``;
}

function currentDataLabel(context: HostContext): string {
  const labels: Record<string, string> = {
    trace: "Trace",
    dbc: "DBC",
    diagnostic: "诊断",
    project: "项目",
  };
  return labels[context.selection_kind ?? ""] ?? "数据";
}

export default function App() {
  const [context, setContext] = useState<HostContext>(emptyContext);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [isRunning, setIsRunning] = useState(false);
  const [contextLoading, setContextLoading] = useState(true);
  const [artifacts, setArtifacts] = useState<CopilotArtifact[]>([]);
  const [composerAttachmentCount, setComposerAttachmentCount] = useState(0);
  const hostConnected = Boolean(context.host_application);
  const hasCurrentData = Boolean(context.selection_kind && context.snapshot_revision);
  const dataLabel = currentDataLabel(context);

  const attachmentAdapter = useMemo(() => {
    const adapter = new SimpleTextAttachmentAdapter();
    adapter.accept = attachmentAccept;
    return adapter;
  }, []);

  const appendAssistant = useCallback((content: string) => {
    setMessages((current) => [...current, assistantMessage(content)]);
  }, []);

  const reportError = useCallback(
    (error: unknown) => {
      const requestId = error instanceof GatewayRequestError ? error.requestId : undefined;
      const message = error instanceof Error ? error.message : "请求失败";
      appendAssistant(
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
    async (message: ChatMessage, action: () => Promise<string>) => {
      if (isRunning) return;
      setMessages((current) => [...current, message]);
      setIsRunning(true);
      try {
        appendAssistant(await action());
      } catch (error) {
        reportError(error);
      } finally {
        setIsRunning(false);
      }
    },
    [appendAssistant, isRunning, reportError],
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
      task: "chat" | "generate_test",
      displayAttachments?: readonly CompleteAttachment[],
    ) =>
      run(userMessage(question, displayAttachments), async () => {
        const payload = await gatewayClient.queryCopilot(question, attachments, task);
        if (payload.artifacts.length) setArtifacts(payload.artifacts);
        return formatCopilotResponse(payload);
      }),
    [run],
  );

  const suggestions = useMemo(() => {
    if (composerAttachmentCount) {
      return [
        { prompt: "解释已添加文件的主要逻辑和风险。" },
        { prompt: "基于已添加文件生成覆盖关键分支的 pytest 测试。" },
      ];
    }
    if (hasCurrentData) {
      return [{ prompt: `分析当前 ${dataLabel} 的异常和风险。` }];
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

  const generateTests = useCallback(() => {
    const composer = runtime.thread.composer;
    if (!composer.getState().attachments.length) return;
    composer.setText("基于已添加文件生成可运行的 pytest 测试代码。");
    composer.setRunConfig({ custom: { task: "generate_test" } });
    composer.send();
  }, [runtime]);

  const downloadArtifact = useCallback((artifact: CopilotArtifact) => {
    const url = URL.createObjectURL(new Blob([artifact.content], { type: "text/x-python" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = artifact.name;
    link.click();
    URL.revokeObjectURL(url);
  }, []);

  return (
    <FluentProvider theme={webLightTheme} className="app-provider">
      <main className="copilot-shell">
        <header className="shell-header">
          <div className="brand-block">
            <span className="brand-mark" aria-hidden="true">
              <Sparkle20Filled />
            </span>
            <div className="brand-copy">
              <h1>CoreTest Copilot</h1>
              <p>{context.host_application || "未连接 CoreTest"}</p>
            </div>
          </div>
          <Tooltip content="刷新宿主上下文" relationship="label">
            <Button
              appearance="subtle"
              icon={contextLoading ? <Spinner size="tiny" /> : <ArrowSync20Regular />}
              aria-label="刷新宿主上下文"
              onClick={() => void refreshContext()}
              disabled={contextLoading}
            />
          </Tooltip>
        </header>

        <section className="context-strip" aria-label="宿主上下文">
          {hostConnected ? (
            <div className="context-main">
              <div>
                <span className="context-label">项目</span>
                <strong>{context.project_id || "未打开项目"}</strong>
              </div>
              <div>
                <span className="context-label">当前数据</span>
                <strong>{context.selection_label || context.current_view || "未选择"}</strong>
              </div>
            </div>
          ) : (
            <div className="context-empty">未连接 CoreTest</div>
          )}
          <Badge
            appearance="tint"
            color={hostConnected ? "success" : "informative"}
            icon={hostConnected ? <ShieldCheckmark20Regular /> : undefined}
          >
            {hostConnected ? "只读" : "独立模式"}
          </Badge>
        </section>

        <div className="quick-actions" aria-label="快捷操作">
          <Button
            appearance="secondary"
            icon={<ChartMultiple20Regular />}
            disabled={isRunning || !hasCurrentData}
            onClick={() => void analyze(`分析当前 ${dataLabel} 的异常和风险，并给出下一步排查建议。`)}
          >
            分析当前 {dataLabel}
          </Button>
          <Button
            appearance="primary"
            icon={<Code20Regular />}
            disabled={isRunning || composerAttachmentCount === 0}
            onClick={generateTests}
          >
            生成测试
          </Button>
          {artifacts.map((artifact) => (
            <Button
              key={artifact.name}
              appearance="subtle"
              icon={<ArrowDownload20Regular />}
              onClick={() => downloadArtifact(artifact)}
            >
              保存 {artifact.name}
            </Button>
          ))}
        </div>

        <section className="chat-region" aria-label="Copilot 对话">
          <AssistantRuntimeProvider runtime={runtime}>
            <Thread
              welcome={{ message: null }}
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
                      ? "询问当前 CoreTest 数据或添加参考文件..."
                      : "输入问题或添加参考文件...",
                  },
                  addAttachment: { tooltip: "添加参考文件" },
                  send: { tooltip: "发送" },
                  cancel: { tooltip: "停止" },
                },
                assistantMessage: { copy: { tooltip: "复制" } },
              }}
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
