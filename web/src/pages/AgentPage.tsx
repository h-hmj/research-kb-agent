import { useEffect, useRef, useState } from "react";

import { streamAgent } from "../api/agent";
import { askQa } from "../api/qa";
import { getLastRequestId, userMessage } from "../api/client";
import { listDocuments } from "../api/documents";
import type {
  AgentMetrics,
  AgentWorkflow,
  Citation,
  DocumentSummary,
} from "../api/types";
import { CitationCard } from "../components/CitationCard";
import { DocumentFilter } from "../components/DocumentFilter";

type Mode = "qa" | "agent";
type RunStatus = "idle" | "loading" | "answered" | "refused" | "error";

const STEP_DEFS: Array<{ id: string; label: string; optional?: boolean }> = [
  { id: "retrieve_initial", label: "初次检索" },
  { id: "assess_initial_evidence", label: "证据判断" },
  { id: "rewrite_query", label: "问题改写", optional: true },
  { id: "retrieve_retry", label: "二次检索", optional: true },
  { id: "assess_retry_evidence", label: "二次证据复核", optional: true },
  { id: "answer", label: "生成回答" },
  { id: "refuse", label: "明确拒答" },
];

export function AgentPage({
  onPreview,
}: {
  onPreview: (id: string, filename: string, page: number) => void;
}) {
  const [mode, setMode] = useState<Mode>("agent");
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(5);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [enableRewrite, setEnableRewrite] = useState(true);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [refusalReason, setRefusalReason] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [workflow, setWorkflow] = useState<AgentWorkflow | null>(null);
  const [metrics, setMetrics] = useState<AgentMetrics | null>(null);
  const [visitedSteps, setVisitedSteps] = useState<string[]>([]);
  const [activeStep, setActiveStep] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;
    listDocuments()
      .then((payload) => {
        if (active) {
          setDocuments(payload.items);
        }
      })
      .catch(() => {
        // The question form remains usable even if the filter list fails.
      });
    return () => {
      active = false;
      controllerRef.current?.abort();
    };
  }, []);

  const resetResult = () => {
    setAnswer("");
    setCitations([]);
    setRefusalReason(null);
    setError(null);
    setWorkflow(null);
    setMetrics(null);
    setVisitedSteps([]);
    setActiveStep(null);
    setRequestId(null);
    setCopied(false);
  };

  const run = async () => {
    const trimmed = question.trim();
    if (!trimmed || status === "loading") {
      return;
    }
    if (topK < 1 || topK > 20) {
      setError("top_k 必须在 1 到 20 之间。");
      return;
    }
    resetResult();
    setStatus("loading");
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      if (mode === "qa") {
        const response = await askQa(trimmed, topK, selectedDocs);
        setStatus(response.status);
        setAnswer(response.answer);
        setCitations(response.citations);
        setRefusalReason(response.refusal_reason);
        setRequestId(getLastRequestId());
      } else {
        let sawTerminalEvent = false;
        for await (const event of streamAgent(
          trimmed,
          topK,
          selectedDocs,
          enableRewrite,
          controller.signal,
        )) {
          if (event.event === "workflow") {
            setRequestId(event.data.request_id);
            if (
              event.data.step !== "request_received" &&
              event.data.step !== "completed"
            ) {
              setVisitedSteps((current) =>
                current.includes(event.data.step)
                  ? current
                  : [...current, event.data.step],
              );
              setActiveStep(event.data.step);
            }
            if (event.data.step === "completed") {
              setActiveStep(null);
            }
          } else if (event.event === "token") {
            if (event.data.content) {
              setAnswer((current) => current + event.data.content);
            }
          } else if (event.event === "citations") {
            setCitations(event.data.citations);
          } else if (event.event === "final") {
            sawTerminalEvent = true;
            setStatus(event.data.status);
            setRefusalReason(event.data.refusal_reason);
            setWorkflow(event.data.workflow);
            setMetrics(event.data.metrics);
            setRequestId(event.data.request_id);
            setVisitedSteps(event.data.workflow.steps);
            setActiveStep(null);
          } else if (event.event === "error") {
            sawTerminalEvent = true;
            setStatus("error");
            setError(event.data.message);
            setRequestId(event.data.request_id);
          }
        }
        if (!sawTerminalEvent) {
          setStatus("error");
          setError("流式连接已结束，但没有收到 final 事件。");
        }
      }
    } catch (requestError: unknown) {
      if (
        requestError instanceof DOMException &&
        requestError.name === "AbortError"
      ) {
        return;
      }
      setStatus("error");
      setError(userMessage(requestError));
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  };

  const copyRequestId = async () => {
    if (!requestId) {
      return;
    }
    try {
      await navigator.clipboard.writeText(requestId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  const isAgent = mode === "agent";
  const showAnswerCard =
    status === "refused" ||
    status === "answered" ||
    (status === "loading" && answer.length > 0);
  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">TRACEABLE ANSWERING</p>
          <h1>Agent 问答</h1>
          <p className="lede">
            观察检索、证据判断、问题改写和流式回答；所有引用由服务端返回。
          </p>
        </div>
        <div className="mode-switch" role="group" aria-label="问答模式">
          <button
            type="button"
            className={mode === "qa" ? "active" : ""}
            onClick={() => setMode("qa")}
            disabled={status === "loading"}
          >
            基础 QA
          </button>
          <button
            type="button"
            className={mode === "agent" ? "active" : ""}
            onClick={() => setMode("agent")}
            disabled={status === "loading"}
          >
            LangGraph Agent
          </button>
        </div>
      </header>

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">QUESTION</p>
            <h2>{isAgent ? "带二次检索的单轮问答" : "单次检索后直接回答"}</h2>
          </div>
          <span className="muted">{question.length} / 2000</span>
        </div>
        <textarea
          className="question-input"
          value={question}
          maxLength={2000}
          rows={4}
          placeholder="例如：实验中为什么需要设置空白对照？"
          onChange={(event) => setQuestion(event.target.value)}
          disabled={status === "loading"}
        />
        <div className="form-grid compact-grid">
          <label className="field">
            <span>Top K</span>
            <input
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value))}
              disabled={status === "loading"}
            />
          </label>
          <DocumentFilter
            documents={documents}
            selected={selectedDocs}
            onChange={setSelectedDocs}
          />
          {isAgent ? (
            <label className="check-field">
              <input
                type="checkbox"
                checked={enableRewrite}
                onChange={(event) => setEnableRewrite(event.target.checked)}
                disabled={status === "loading"}
              />
              允许问题改写（最多一次）
            </label>
          ) : null}
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="primary-button"
            disabled={status === "loading" || question.trim().length === 0}
            onClick={() => void run()}
          >
            {status === "loading" ? "正在处理…" : "提问"}
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={status === "loading"}
            onClick={() => {
              resetResult();
              setQuestion("");
              setStatus("idle");
            }}
          >
            清空
          </button>
        </div>
        <p className="hint">
          {isAgent
            ? "请求会以 SSE 流式返回；只展示后端提供的安全 workflow 节点。"
            : "基础 QA 只做一次检索，不显示 Agent 流程，可用于对比。"}
        </p>
      </section>

      {isAgent ? (
        <section className="card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">WORKFLOW</p>
              <h2>Agent 执行流程</h2>
            </div>
            {activeStep ? <span className="badge badge-info">进行中</span> : null}
          </div>
          <div className="workflow-strip">
            {STEP_DEFS.map((step) => {
              const visited = visitedSteps.includes(step.id);
              const active = activeStep === step.id;
              const missingOptional =
                step.optional && !visited && status !== "loading";
              return (
                <div
                  key={step.id}
                  className={`workflow-node ${
                    active ? "active" : visited ? "done" : "pending"
                  } ${missingOptional ? "skipped" : ""}`}
                >
                  <span className="workflow-index">
                    {active ? "•" : visited ? "✓" : "—"}
                  </span>
                  <span>{step.label}</span>
                  {missingOptional ? <small>未触发</small> : null}
                </div>
              );
            })}
          </div>
          <p className="hint">
            未触发的改写或二次检索保持灰色；界面不会推断未返回的节点。
          </p>
        </section>
      ) : null}

      {status === "error" ? (
        <p className="notice notice-error">{error ?? "流式请求失败。"}</p>
      ) : null}

      {showAnswerCard ? (
        <section className="card answer-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">ANSWER</p>
              <h2>
                {status === "refused"
                  ? "已拒答"
                  : status === "loading"
                    ? "正在生成回答"
                    : "生成结果"}
              </h2>
            </div>
            <span
              className={`badge ${
                status === "refused"
                  ? "badge-warning"
                  : status === "loading"
                    ? "badge-info"
                    : "badge-success"
              }`}
            >
              {status === "refused"
                ? "无足够证据"
                : status === "loading"
                  ? "流式生成中"
                  : "回答完成"}
            </span>
          </div>
          {status === "refused" ? (
            <div className="refusal-box">
              <strong>无法根据已检索到的资料回答该问题。</strong>
              {refusalReason ? <p>{refusalReason}</p> : null}
            </div>
          ) : (
            <p className={`answer-text ${status === "loading" ? "streaming" : ""}`}>
              {answer}
            </p>
          )}
          {status === "answered" && citations.length > 0 ? (
            <div className="citations">
              <h3>页码级引用</h3>
              {citations.map((citation) => (
                <CitationCard
                  key={citation.citation_id}
                  citation={citation}
                  onPreview={onPreview}
                />
              ))}
            </div>
          ) : null}
          <div className="answer-meta">
            {requestId ? (
              <span>
                request_id: <code>{requestId}</code>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => void copyRequestId()}
                >
                  {copied ? "已复制" : "复制"}
                </button>
              </span>
            ) : null}
            {metrics ? (
              <span>
                总耗时 {metrics.total_duration_ms.toFixed(0)} ms · 检索{" "}
                {metrics.retrieval_duration_ms.toFixed(0)} ms · LLM{" "}
                {metrics.llm_duration_ms.toFixed(0)} ms
              </span>
            ) : null}
            {workflow ? (
              <span>
                检索 {workflow.initial_retrieval_count} / 二次{" "}
                {workflow.final_retrieval_count} · 证据 {workflow.evidence_count}
              </span>
            ) : null}
          </div>
        </section>
      ) : null}

      {status === "loading" && isAgent && answer.length === 0 ? (
        <p className="empty-state">正在连接 Agent 工作流…</p>
      ) : null}
    </div>
  );
}
