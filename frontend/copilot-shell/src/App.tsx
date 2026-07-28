import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
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
  ArrowSync20Regular,
  ChartMultiple20Regular,
  ArrowDownload20Regular,
  Attach20Regular,
  Code20Regular,
  Delete16Regular,
  ShieldCheckmark20Regular,
  Sparkle20Filled,
} from "@fluentui/react-icons";
import { GatewayRequestError, gatewayClient, hostSessionId } from "./gatewayClient";
import type {
  AgentResponse,
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
}

const parentOrigin = resolveParentOrigin();
const MarkdownText = makeMarkdownText();

const emptyContext: HostContext = {
  host_session_id: hostSessionId,
  project_id: "未连接",
  run_id: "未选择",
  current_view: "",
  user_id: "",
};

const initialMessages: ChatMessage[] = [
  {
    id: crypto.randomUUID(),
    role: "assistant",
    content:
      "我是 CoreTest Copilot。你可以直接提问，或添加代码、配置、DBC、ASC 等文本文件，让我基于文件生成 pytest 测试代码。",
  },
];

function assistantMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "assistant", content };
}

function userMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "user", content };
}

function convertMessage(message: ChatMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
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

function formatAgentResponse(payload: AgentResponse): string {
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

export default function App() {
  const [context, setContext] = useState<HostContext>(emptyContext);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [isRunning, setIsRunning] = useState(false);
  const [contextLoading, setContextLoading] = useState(true);
  const [attachments, setAttachments] = useState<CopilotAttachment[]>([]);
  const [artifacts, setArtifacts] = useState<CopilotArtifact[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

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
    async (label: string, action: () => Promise<string>) => {
      if (isRunning) return;
      setMessages((current) => [...current, userMessage(label)]);
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
      run(question, async () => formatAgentResponse(await gatewayClient.queryAgent(question))),
    [run],
  );

  const askCopilot = useCallback(
    (question: string, task: "chat" | "generate_test" = "chat") =>
      run(question, async () => {
        const payload = await gatewayClient.queryCopilot(question, attachments, task);
        if (payload.artifacts.length) setArtifacts(payload.artifacts);
        return formatCopilotResponse(payload);
      }),
    [attachments, run],
  );

  const addFiles = useCallback(
    async (files: FileList | null) => {
      if (!files) return;
      try {
        const next = [...attachments];
        for (const file of Array.from(files)) {
          if (file.size > 256 * 1024) throw new Error(`${file.name} 超过 256 KiB`);
          const content = await file.text();
          const item = { name: file.name, content, size: file.size };
          const index = next.findIndex((current) => current.name === file.name);
          if (index >= 0) next[index] = item;
          else next.push(item);
        }
        if (next.length > 5) throw new Error("最多添加 5 个文件");
        setAttachments(next);
      } catch (error) {
        reportError(error);
      } finally {
        if (fileInput.current) fileInput.current.value = "";
      }
    },
    [attachments, reportError],
  );

  const downloadArtifact = useCallback((artifact: CopilotArtifact) => {
    const url = URL.createObjectURL(new Blob([artifact.content], { type: "text/x-python" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = artifact.name;
    link.click();
    URL.revokeObjectURL(url);
  }, []);

  const suggestions = useMemo(
    () => [
      { title: "解释当前文件", message: "解释已添加文件的主要逻辑和风险。", isLoading: false },
      { title: "生成测试", message: "基于已添加文件生成覆盖关键分支的 pytest 测试。", isLoading: false },
    ],
    [],
  );

  const runtime = useExternalStoreRuntime<ChatMessage>({
    messages,
    isRunning,
    convertMessage,
    onNew: async (message) => {
      const question = messageText(message);
      if (question) await askCopilot(question);
    },
    suggestions: suggestions.map((suggestion) => ({ prompt: suggestion.message })),
  });

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
              <p>{context.host_application || "AI Gateway"}</p>
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
          <div className="context-main">
            <div>
              <span className="context-label">项目</span>
              <strong>{context.project_id}</strong>
            </div>
            <div>
              <span className="context-label">当前视图</span>
              <strong>{context.selection_label || context.current_view || "未选择"}</strong>
            </div>
          </div>
          <Badge appearance="tint" color="success" icon={<ShieldCheckmark20Regular />}>
            只读
          </Badge>
        </section>

        <div className="quick-actions" aria-label="快捷分析">
          <Button
            appearance="secondary"
            icon={<ChartMultiple20Regular />}
            disabled={isRunning}
            onClick={() => void analyze("分析当前测试失败原因，并给出下一步排查建议。")}
          >
            分析当前界面
          </Button>
          <input
            ref={fileInput}
            className="file-input"
            type="file"
            multiple
            accept=".py,.json,.yaml,.yml,.xml,.txt,.dbc,.md,.toml,.ini,.cfg,.csv,.log,.asc"
            onChange={(event) => void addFiles(event.target.files)}
          />
          <Button
            appearance="secondary"
            icon={<Attach20Regular />}
            disabled={isRunning}
            onClick={() => fileInput.current?.click()}
          >
            添加文件
          </Button>
          <Button
            appearance="primary"
            icon={<Code20Regular />}
            disabled={isRunning || attachments.length === 0}
            onClick={() => void askCopilot("基于已添加文件生成可运行的 pytest 测试代码。", "generate_test")}
          >
            生成测试
          </Button>
        </div>

        {(attachments.length > 0 || artifacts.length > 0) && (
          <section className="work-files" aria-label="工作文件">
            {attachments.map((attachment) => (
              <div className="file-pill" key={attachment.name}>
                <span title={attachment.name}>{attachment.name}</span>
                <Button
                  appearance="subtle"
                  size="small"
                  icon={<Delete16Regular />}
                  aria-label={`移除 ${attachment.name}`}
                  onClick={() =>
                    setAttachments((current) => current.filter((item) => item.name !== attachment.name))
                  }
                />
              </div>
            ))}
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
          </section>
        )}

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
              composer={{ allowAttachments: false }}
              strings={{
                thread: { scrollToBottom: { tooltip: "滚动到底部" } },
                composer: {
                  input: { placeholder: attachments.length ? "询问已添加文件..." : "询问 CoreTest 或当前项目..." },
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
