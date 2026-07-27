import { useCallback, useEffect, useMemo, useState } from "react";
import type { ComponentProps } from "react";
import { CopilotChatView } from "@copilotkit/react-core/v2";
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
  ArrowSwap20Regular,
  DataTrending20Regular,
  ShieldCheckmark20Regular,
  Sparkle20Filled,
} from "@fluentui/react-icons";
import { GatewayRequestError, gatewayClient, hostSessionId } from "./gatewayClient";
import type {
  AnalysisResponse,
  HostContext,
  HostContextMessage,
  InsightsResponse,
} from "./types";

type ChatMessages = NonNullable<ComponentProps<typeof CopilotChatView>["messages"]>;
type ChatMessage = ChatMessages[number];

const emptyContext: HostContext = {
  host_session_id: hostSessionId,
  project_id: "未连接",
  run_id: "未选择",
  current_view: "",
  user_id: "",
};

const initialMessages: ChatMessages = [
  {
    id: crypto.randomUUID(),
    role: "assistant",
    content:
      "我是测试分析 Copilot。已连接 AI Gateway，可以分析当前测试、生成确定性数据洞察，或比较两次测试结果。",
  },
];

function assistantMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "assistant", content };
}

function userMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "user", content };
}

function formatAnalysis(payload: AnalysisResponse): string {
  const citation = payload.citations[0];
  const source = citation
    ? `\n\n**参考**：[${citation.title}](${citation.source_url}) · ${citation.provider}`
    : "";
  const warning = payload.warnings.length ? `\n\n> ${payload.warnings.join("；")}` : "";
  return `${payload.answer}${source}${warning}\n\n\`request_id: ${payload.request_id}\``;
}

function formatInsights(payload: InsightsResponse): string {
  const statuses = payload.result.status_counts
    .map((item) => `- ${item.status}: **${item.count}**`)
    .join("\n");
  const reasons = payload.result.failure_reasons.length
    ? payload.result.failure_reasons
        .map((item) => `- ${item.reason}: **${item.count}**`)
        .join("\n")
    : "- 未发现失败原因";
  return [
    `### ${payload.result.run_id} 数据洞察`,
    `分析引擎：\`${payload.result.engine}\``,
    "#### 状态分布",
    statuses,
    "#### 失败原因",
    reasons,
    `\`request_id: ${payload.request_id}\``,
  ].join("\n\n");
}

function formatComparison(payload: Record<string, unknown>, requestId: string): string {
  return [
    "### 测试结果对比",
    "```json",
    JSON.stringify(payload, null, 2),
    "```",
    `\`request_id: ${requestId}\``,
  ].join("\n\n");
}

export default function App() {
  const [context, setContext] = useState<HostContext>(emptyContext);
  const [messages, setMessages] = useState<ChatMessages>(initialMessages);
  const [isRunning, setIsRunning] = useState(false);
  const [contextLoading, setContextLoading] = useState(true);

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
      if (event.source !== window.parent || event.origin !== window.location.origin) return;
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
        window.location.origin,
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
      run(question, async () => formatAnalysis(await gatewayClient.analyze(question, context))),
    [context, run],
  );

  const suggestions = useMemo(
    () => [
      {
        title: "失败原因",
        message: "分析当前测试失败原因，并给出下一步排查建议。",
        isLoading: false,
      },
      { title: "风险摘要", message: "总结当前测试的主要风险和优先级。", isLoading: false },
    ],
    [],
  );

  return (
    <FluentProvider theme={webLightTheme} className="app-provider">
      <main className="copilot-shell">
        <header className="shell-header">
          <div className="brand-block">
            <span className="brand-mark" aria-hidden="true">
              <Sparkle20Filled />
            </span>
            <div className="brand-copy">
              <h1>Geely AI Copilot</h1>
              <p>测试分析助手</p>
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
              <span className="context-label">当前运行</span>
              <strong>{context.run_id}</strong>
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
            分析当前测试
          </Button>
          <Button
            appearance="secondary"
            icon={<DataTrending20Regular />}
            disabled={isRunning || (!context.source_asset_id && !context.source_file)}
            onClick={() =>
              void run("生成当前测试的数据洞察", async () =>
                formatInsights(await gatewayClient.insights(context)),
              )
            }
          >
            数据洞察
          </Button>
          <Button
            appearance="secondary"
            icon={<ArrowSwap20Regular />}
            disabled={
              isRunning ||
              (!context.source_asset_id && !context.source_file) ||
              (!context.target_asset_id && !context.target_file)
            }
            onClick={() =>
              void run("比较当前测试与目标测试", async () => {
                const payload = await gatewayClient.compare(context);
                return formatComparison(payload.result, payload.request_id);
              })
            }
          >
            对比结果
          </Button>
        </div>

        <section className="chat-region" aria-label="Copilot 对话">
          <CopilotChatView
            messages={messages}
            isRunning={isRunning}
            suggestions={suggestions}
            onSelectSuggestion={(suggestion) => void analyze(suggestion.message)}
            onSubmitMessage={(value) => void analyze(value)}
            input={{ textArea: { placeholder: "询问当前测试数据..." } }}
            autoScroll="pin-to-bottom"
          />
        </section>
      </main>
    </FluentProvider>
  );
}
