import {
  ActionBarPrimitive,
  AttachmentPrimitive,
  ComposerPrimitive,
  MessagePartPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useMessage,
} from "@assistant-ui/react";
import { makeMarkdownText } from "@assistant-ui/react-ui";
import {
  ArrowDown20Regular,
  ArrowDownload20Regular,
  ArrowUndo20Regular,
  Bot20Regular,
  Checkmark20Regular,
  CheckmarkCircle20Regular,
  ChevronRight16Regular,
  Code20Regular,
  Copy20Regular,
  Dismiss20Regular,
  Document20Regular,
  History20Regular,
  LockClosed20Regular,
  Play20Regular,
  Send20Regular,
  Settings20Regular,
  Stop20Regular,
  Warning16Regular,
} from "@fluentui/react-icons";
import type {
  AgentActivity,
  AgentDiffResult,
  AgentPermission,
  CopilotArtifact,
  ModelConfig,
} from "./types";

interface RequestDiagnostic {
  detail: string;
  requestId?: string;
}

interface Suggestion {
  prompt: string;
}

export interface AgentThreadProps {
  hostConnected: boolean;
  contextLabel: string;
  dataLabel: string;
  suggestions: Suggestion[];
  isRunning: boolean;
  lastMessageRole?: "assistant" | "user";
  latestAssistantId?: string;
  activity: AgentActivity[];
  permission: AgentPermission | null;
  permissionReplying: boolean;
  onReplyPermission: (reply: "once" | "reject") => void;
  diffResult: AgentDiffResult;
  reverting: boolean;
  onRevert: () => void;
  artifacts: CopilotArtifact[];
  onCopyArtifact: (artifact: CopilotArtifact) => void;
  onDownloadArtifact: (artifact: CopilotArtifact) => void;
  diagnostic: RequestDiagnostic | null;
  saveNotice: string | null;
  composerAttachmentCount: number;
  onGenerateTests: () => void;
  modelConfig: ModelConfig | null;
  modelSaving: boolean;
  onSelectModel: (model: string) => void;
  historyCount: number;
  onOpenHistory: () => void;
  onOpenSettings: () => void;
}

const MarkdownText = makeMarkdownText({
  className: "agent-markdown",
  components: {
    CodeHeader: ({ language, code }) => (
      <div className="code-header">
        <span>{language || "text"}</span>
        <button
          type="button"
          className="icon-button compact"
          aria-label="复制代码"
          title="复制代码"
          onClick={() => void navigator.clipboard.writeText(code || "")}
        >
          <Copy20Regular aria-hidden="true" />
        </button>
      </div>
    ),
  },
});

export function AgentThread(props: AgentThreadProps) {
  const showPending = props.isRunning && props.lastMessageRole === "user";
  const modelOptions = Array.from(new Set([
    ...(props.modelConfig?.model ? [props.modelConfig.model] : []),
    ...(props.modelConfig?.available_models ?? []),
  ]));

  return (
    <ThreadPrimitive.Root className="agent-thread-root">
      <ThreadPrimitive.Viewport className="agent-thread-viewport">
        <ThreadPrimitive.Empty>
          <AgentWelcome
            hostConnected={props.hostConnected}
            contextLabel={props.contextLabel}
            dataLabel={props.dataLabel}
            suggestions={props.suggestions}
          />
        </ThreadPrimitive.Empty>

        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            AssistantMessage: () => <AssistantMessage {...props} />,
          }}
        />

        {showPending && <PendingAgentTurn />}

        <ThreadPrimitive.ViewportFooter className="agent-thread-footer">
          <ThreadPrimitive.ScrollToBottom asChild>
            <button
              type="button"
              className="scroll-bottom-button"
              aria-label="滚动到底部"
              title="滚动到底部"
            >
              <ArrowDown20Regular aria-hidden="true" />
            </button>
          </ThreadPrimitive.ScrollToBottom>

          <AgentComposer
            hostConnected={props.hostConnected}
            attachmentCount={props.composerAttachmentCount}
            isRunning={props.isRunning}
            onGenerateTests={props.onGenerateTests}
          />

          <div className="agent-control-bar" aria-label="Agent 控制栏">
            <label className="model-control" title={props.modelConfig?.model ?? "未配置模型"}>
              <Bot20Regular aria-hidden="true" />
              <select
                aria-label="切换模型"
                value={props.modelConfig?.model ?? ""}
                onChange={(event) => props.onSelectModel(event.target.value)}
                disabled={props.modelSaving || props.isRunning || !props.modelConfig?.configured}
              >
                {!props.modelConfig?.model && <option value="">未配置模型</option>}
                {modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            </label>
            <button
              type="button"
              className="control-button"
              onClick={props.onOpenHistory}
              disabled={props.isRunning}
              title="历史会话"
            >
              <History20Regular aria-hidden="true" />
              <span>历史</span>
              <small>{props.historyCount}</small>
            </button>
            <button
              type="button"
              className="control-button"
              onClick={props.onOpenSettings}
              disabled={props.isRunning || props.modelSaving}
              title="模型与 API 配置"
            >
              <Settings20Regular aria-hidden="true" />
              <span>API</span>
            </button>
          </div>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}

function AgentWelcome({
  hostConnected,
  contextLabel,
  dataLabel,
  suggestions,
}: Pick<AgentThreadProps, "hostConnected" | "contextLabel" | "dataLabel" | "suggestions">) {
  const title = hostConnected ? "从当前工程开始" : "等待 CoreTest 连接";
  const description = hostConnected
    ? "我可以读取工程、分析文件，并在你批准后修改代码或运行命令。"
    : "连接后，Agent 会自动获得当前工程作为唯一工作区。";

  return (
    <section className="agent-welcome">
      <div className="agent-mark">
        <Code20Regular aria-hidden="true" />
      </div>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {hostConnected && contextLabel !== "等待选择" && (
        <div className="welcome-context">
          <Document20Regular aria-hidden="true" />
          <span><strong>{dataLabel}</strong>{contextLabel}</span>
        </div>
      )}
      {suggestions.length > 0 && (
        <div className="welcome-suggestions">
          {suggestions.map((suggestion) => (
            <ThreadPrimitive.Suggestion
              key={suggestion.prompt}
              className="suggestion-button"
              prompt={suggestion.prompt}
              method="replace"
              autoSend
            >
              <span>{suggestion.prompt}</span>
              <ChevronRight16Regular aria-hidden="true" />
            </ThreadPrimitive.Suggestion>
          ))}
        </div>
      )}
    </section>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="user-message-root">
      <MessagePrimitive.Attachments
        components={{ Attachment: MessageAttachment }}
      />
      <div className="user-message-content">
        <MessagePrimitive.Content components={{ Text: UserText }} />
      </div>
    </MessagePrimitive.Root>
  );
}

function UserText() {
  return <MessagePartPrimitive.Text className="user-message-text" />;
}

function AssistantMessage(props: AgentThreadProps) {
  const messageId = useMessage((message) => message.id);
  const isLatest = messageId === props.latestAssistantId;
  const isCurrentTurn = isLatest && props.lastMessageRole !== "user";

  return (
    <MessagePrimitive.Root className="assistant-message-root">
      <div className="assistant-message-header">
        <span className="assistant-badge"><Bot20Regular aria-hidden="true" /></span>
        <strong>Agent</strong>
        {isCurrentTurn && props.isRunning && (
          <span className="running-label"><span className="status-spinner" />正在工作</span>
        )}
      </div>

      {isCurrentTurn && props.activity.length > 0 && (
        <ActivityTimeline activity={props.activity} isRunning={props.isRunning} />
      )}

      {isCurrentTurn && props.permission && (
        <PermissionConfirmation
          permission={props.permission}
          replying={props.permissionReplying}
          onReply={props.onReplyPermission}
        />
      )}

      <div className="assistant-message-content">
        <MessagePrimitive.Content components={{ Text: MarkdownText }} />
      </div>

      {isCurrentTurn && (
        <TurnResults
          diffResult={props.diffResult}
          reverting={props.reverting}
          onRevert={props.onRevert}
          artifacts={props.artifacts}
          onCopyArtifact={props.onCopyArtifact}
          onDownloadArtifact={props.onDownloadArtifact}
          diagnostic={props.diagnostic}
          saveNotice={props.saveNotice}
          isRunning={props.isRunning}
        />
      )}

      <ActionBarPrimitive.Root className="message-action-bar" hideWhenRunning>
        <ActionBarPrimitive.Copy asChild>
          <button type="button" className="message-action" aria-label="复制回答" title="复制回答">
            <Copy20Regular aria-hidden="true" />
          </button>
        </ActionBarPrimitive.Copy>
      </ActionBarPrimitive.Root>
    </MessagePrimitive.Root>
  );
}

function PendingAgentTurn() {
  return (
    <div className="assistant-message-root pending-turn" role="status">
      <div className="assistant-message-header">
        <span className="assistant-badge"><Bot20Regular aria-hidden="true" /></span>
        <strong>Agent</strong>
        <span className="running-label"><span className="status-spinner" />正在理解任务</span>
      </div>
      <div className="pending-lines" aria-hidden="true"><span /><span /><span /></div>
    </div>
  );
}

function ActivityTimeline({ activity, isRunning }: { activity: AgentActivity[]; isRunning: boolean }) {
  const runningStep = [...activity].reverse().find((step) => isActiveStep(step.status));
  const completed = activity.filter((step) => !isActiveStep(step.status)).length;
  const summary = runningStep
    ? `${toolLabel(runningStep.tool)}：${runningStep.title}`
    : `已完成 ${completed} 个步骤`;

  return (
    <details className="activity-timeline" open={isRunning}>
      <summary>
        <span className={runningStep ? "status-spinner" : "status-check"}>
          {!runningStep && <Checkmark20Regular aria-hidden="true" />}
        </span>
        <span>{summary}</span>
        <small>{activity.length}</small>
        <ChevronRight16Regular className="details-chevron" aria-hidden="true" />
      </summary>
      <div className="activity-steps">
        {activity.map((step) => (
          <div className="activity-step" key={step.id}>
            <span className="activity-rail">
              {isActiveStep(step.status)
                ? <span className="status-spinner" />
                : <Checkmark20Regular aria-hidden="true" />}
            </span>
            <div>
              <strong>{toolLabel(step.tool)}</strong>
              <code title={step.title}>{step.title}</code>
              {step.output && (
                <details className="tool-output">
                  <summary>查看输出</summary>
                  <pre>{step.output}</pre>
                </details>
              )}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

function PermissionConfirmation({
  permission,
  replying,
  onReply,
}: {
  permission: AgentPermission;
  replying: boolean;
  onReply: (reply: "once" | "reject") => void;
}) {
  return (
    <section className="permission-confirmation" role="alert" aria-label="智能体操作审批">
      <div className="permission-icon"><LockClosed20Regular aria-hidden="true" /></div>
      <div className="permission-copy">
        <strong>{permissionLabel(permission.permission)}</strong>
        <span>Agent 需要你的确认才能继续</span>
        {permission.resources.length > 0 && (
          <div className="permission-resources">
            {permission.resources.map((resource) => <code key={resource}>{resource}</code>)}
          </div>
        )}
      </div>
      <div className="permission-actions">
        <button type="button" className="secondary-button" onClick={() => onReply("reject")} disabled={replying}>
          拒绝
        </button>
        <button type="button" className="primary-button" onClick={() => onReply("once")} disabled={replying}>
          <Play20Regular aria-hidden="true" />允许一次
        </button>
      </div>
    </section>
  );
}

function TurnResults({
  diffResult,
  reverting,
  onRevert,
  artifacts,
  onCopyArtifact,
  onDownloadArtifact,
  diagnostic,
  saveNotice,
  isRunning,
}: Pick<
  AgentThreadProps,
  | "diffResult"
  | "reverting"
  | "onRevert"
  | "artifacts"
  | "onCopyArtifact"
  | "onDownloadArtifact"
  | "diagnostic"
  | "saveNotice"
  | "isRunning"
>) {
  const hasDiff = diffResult.files.length > 0
    || diffResult.revert_reason === "workspace_has_no_git_baseline";

  return (
    <>
      {hasDiff && (
        <section className="checkpoint-panel" aria-label="本轮文件变更">
          <div className="checkpoint-heading">
            <div className="checkpoint-icon"><Code20Regular aria-hidden="true" /></div>
            <div>
              <strong>工作区检查点</strong>
              <span>
                {diffResult.files.length > 0
                  ? `${diffResult.files.length} 个文件发生变更`
                  : "修改已完成，但当前工程没有 Git 基线"}
              </span>
            </div>
            {diffResult.revert_available && (
              <button
                type="button"
                className="checkpoint-revert"
                onClick={onRevert}
                disabled={reverting || isRunning}
                title="撤销本轮修改"
              >
                <ArrowUndo20Regular aria-hidden="true" />
                <span>{reverting ? "撤销中" : "撤销"}</span>
              </button>
            )}
          </div>

          {diffResult.revert_reason === "workspace_has_no_git_baseline" && (
            <div className="inline-warning" role="note">
              <Warning16Regular aria-hidden="true" />
              <span>无法自动撤销，请使用工程自身的版本管理能力检查变更。</span>
            </div>
          )}

          {diffResult.files.length > 0 && (
            <div className="changed-files">
              {diffResult.files.map((file) => (
                <details key={file.path}>
                  <summary>
                    <ChevronRight16Regular className="details-chevron" aria-hidden="true" />
                    <code title={file.path}>{file.path}</code>
                    <span className="diff-additions">+{file.additions}</span>
                    <span className="diff-deletions">-{file.deletions}</span>
                  </summary>
                  <pre>{file.patch || "未返回文本补丁"}</pre>
                  {file.truncated && <small>补丁过长，已截断显示</small>}
                </details>
              ))}
            </div>
          )}
        </section>
      )}

      {artifacts.length > 0 && (
        <section className="artifact-list" aria-label="生成结果">
          {artifacts.map((artifact) => (
            <div className="artifact-row" key={artifact.name}>
              <span className="artifact-icon"><Document20Regular aria-hidden="true" /></span>
              <div><strong>{artifact.name}</strong><span>{artifact.language}</span></div>
              <button
                type="button"
                className="icon-button compact"
                onClick={() => onCopyArtifact(artifact)}
                aria-label={`复制 ${artifact.name}`}
                title="复制代码"
              >
                <Copy20Regular aria-hidden="true" />
              </button>
              <button
                type="button"
                className="icon-button compact primary-icon"
                onClick={() => onDownloadArtifact(artifact)}
                aria-label={`保存 ${artifact.name}`}
                title="保存到 generated_tests"
              >
                <ArrowDownload20Regular aria-hidden="true" />
              </button>
            </div>
          ))}
        </section>
      )}

      {(saveNotice || diagnostic) && (
        <div className="turn-status" role="status">
          {saveNotice && (
            <span className="success-notice">
              <CheckmarkCircle20Regular aria-hidden="true" />{saveNotice}
            </span>
          )}
          {diagnostic && (
            <details className="diagnostic-details">
              <summary><Warning16Regular aria-hidden="true" />诊断详情</summary>
              <p>{diagnostic.detail}</p>
              {diagnostic.requestId && (
                <div className="request-id-row">
                  <code title={diagnostic.requestId}>{diagnostic.requestId}</code>
                  <button
                    type="button"
                    className="icon-button compact"
                    aria-label="复制 request ID"
                    title="复制 request ID"
                    onClick={() => void navigator.clipboard.writeText(diagnostic.requestId || "")}
                  >
                    <Copy20Regular aria-hidden="true" />
                  </button>
                </div>
              )}
            </details>
          )}
        </div>
      )}
    </>
  );
}

function AgentComposer({
  hostConnected,
  attachmentCount,
  isRunning,
  onGenerateTests,
}: {
  hostConnected: boolean;
  attachmentCount: number;
  isRunning: boolean;
  onGenerateTests: () => void;
}) {
  return (
    <ComposerPrimitive.Root className="agent-composer">
      <ComposerPrimitive.Attachments
        components={{ Attachment: ComposerAttachment }}
      />
      <div className="composer-main-row">
        <ComposerPrimitive.AddAttachment asChild>
          <button type="button" className="composer-tool-button" aria-label="添加参考文件" title="添加参考文件">
            <Document20Regular aria-hidden="true" />
          </button>
        </ComposerPrimitive.AddAttachment>
        <ComposerPrimitive.Input
          rows={1}
          className="composer-input"
          placeholder={hostConnected ? "让 Agent 分析、修改或运行当前工程…" : "输入问题…"}
        />
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send asChild>
            <button type="button" className="composer-send-button" aria-label="发送" title="发送">
              <Send20Regular aria-hidden="true" />
            </button>
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel asChild>
            <button type="button" className="composer-send-button cancel" aria-label="停止" title="停止">
              <Stop20Regular aria-hidden="true" />
            </button>
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
      </div>
      <div className="composer-meta-row">
        <span>{hostConnected ? "工作区已连接" : "等待工作区"}</span>
        {attachmentCount > 0 && (
          <button type="button" onClick={onGenerateTests} disabled={isRunning}>
            <Code20Regular aria-hidden="true" />生成并验证测试
          </button>
        )}
      </div>
    </ComposerPrimitive.Root>
  );
}

function ComposerAttachment() {
  return (
    <AttachmentPrimitive.Root className="composer-attachment">
      <Document20Regular aria-hidden="true" />
      <AttachmentPrimitive.Name />
      <AttachmentPrimitive.Remove asChild>
        <button type="button" aria-label="移除附件" title="移除附件">
          <Dismiss20Regular aria-hidden="true" />
        </button>
      </AttachmentPrimitive.Remove>
    </AttachmentPrimitive.Root>
  );
}

function MessageAttachment() {
  return (
    <AttachmentPrimitive.Root className="message-attachment">
      <Document20Regular aria-hidden="true" />
      <AttachmentPrimitive.Name />
    </AttachmentPrimitive.Root>
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
    write: "写入文件",
    apply_patch: "应用修改",
    bash: "运行命令",
  };
  return labels[tool] ?? tool;
}

function isActiveStep(status: string): boolean {
  return status === "running" || status === "pending";
}
