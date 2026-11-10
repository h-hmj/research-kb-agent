import { useEffect, useState } from "react";

import { userMessage } from "../api/client";
import { listDocuments } from "../api/documents";
import { runChecklist, summarizeMeeting } from "../api/tools";
import type {
  ChecklistResult,
  DocumentSummary,
  MeetingSummaryResult,
  ToolResponse,
} from "../api/types";
import { CitationCard } from "../components/CitationCard";
import { DocumentFilter } from "../components/DocumentFilter";
import { StatusBadge } from "../components/StatusBadge";

type ToolTab = "checklist" | "meeting";

const categoryLabels: Record<string, string> = {
  preparation: "准备",
  operation: "操作",
  recording: "记录",
  review: "复核",
};

const priorityLabels: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

function isChecklistResult(
  result: ToolResponse["result"],
): result is ChecklistResult {
  return "items" in result && "title" in result;
}

function isMeetingResult(
  result: ToolResponse["result"],
): result is MeetingSummaryResult {
  return "summary" in result && "action_items" in result;
}

export function ToolsPage({
  onPreview,
}: {
  onPreview: (id: string, filename: string, page: number) => void;
}) {
  const [tab, setTab] = useState<ToolTab>("checklist");
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [goal, setGoal] = useState("");
  const [constraints, setConstraints] = useState<string[]>([]);
  const [constraintDraft, setConstraintDraft] = useState("");
  const [checklistTopK, setChecklistTopK] = useState(5);
  const [checklistResponse, setChecklistResponse] =
    useState<ToolResponse | null>(null);
  const [meetingTitle, setMeetingTitle] = useState("");
  const [meetingFocus, setMeetingFocus] = useState("");
  const [meetingText, setMeetingText] = useState("");
  const [meetingResponse, setMeetingResponse] =
    useState<ToolResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listDocuments()
      .then((payload) => {
        if (active) {
          setDocuments(payload.items);
        }
      })
      .catch(() => {
        // Keep the tool usable even if document filtering is unavailable.
      });
    return () => {
      active = false;
    };
  }, []);

  const addConstraint = () => {
    const value = constraintDraft.trim();
    if (!value || constraints.includes(value)) {
      return;
    }
    if (constraints.length >= 20) {
      setError("约束条件最多 20 条。");
      return;
    }
    setConstraints((current) => [...current, value]);
    setConstraintDraft("");
  };

  const submitChecklist = async () => {
    if (!goal.trim() || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    setChecklistResponse(null);
    try {
      setChecklistResponse(
        await runChecklist(goal.trim(), constraints, checklistTopK, selectedDocs),
      );
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  const submitMeeting = async () => {
    if (!meetingText.trim() || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    setMeetingResponse(null);
    try {
      setMeetingResponse(
        await summarizeMeeting(meetingTitle, meetingFocus, meetingText),
      );
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">CONTROLLED TOOLS</p>
          <h1>科研工具</h1>
          <p className="lede">
            工具由 API 显式指定；一次请求只执行一个工具，引用仍由服务端生成。
          </p>
        </div>
        <div className="mode-switch">
          <button
            type="button"
            className={tab === "checklist" ? "active" : ""}
            onClick={() => {
              setTab("checklist");
              setError(null);
            }}
          >
            实验 Checklist
          </button>
          <button
            type="button"
            className={tab === "meeting" ? "active" : ""}
            onClick={() => {
              setTab("meeting");
              setError(null);
            }}
          >
            组会总结
          </button>
        </div>
      </header>

      {error ? <p className="notice notice-error">{error}</p> : null}

      {tab === "checklist" ? (
        <>
          <section className="card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">CHECKLIST</p>
                <h2>基于知识库证据生成实验准备清单</h2>
              </div>
              <span className="badge badge-info">证据驱动</span>
            </div>
            <label className="field">
              <span>实验目标</span>
              <textarea
                rows={3}
                maxLength={1000}
                value={goal}
                placeholder="例如：比较不同温度对酶活性的影响"
                onChange={(event) => setGoal(event.target.value)}
                disabled={loading}
              />
            </label>
            <div className="field">
              <span>约束条件（可选）</span>
              <div className="inline-input">
                <input
                  value={constraintDraft}
                  maxLength={500}
                  placeholder="例如：样品数量有限"
                  onChange={(event) => setConstraintDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addConstraint();
                    }
                  }}
                  disabled={loading}
                />
                <button
                  type="button"
                  className="secondary-button"
                  onClick={addConstraint}
                  disabled={loading}
                >
                  添加
                </button>
              </div>
              {constraints.length > 0 ? (
                <div className="tag-list">
                  {constraints.map((item) => (
                    <button
                      key={item}
                      type="button"
                      className="tag"
                      onClick={() =>
                        setConstraints((current) =>
                          current.filter((value) => value !== item),
                        )
                      }
                      title="点击移除"
                    >
                      {item} ×
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <div className="form-grid">
              <label className="field">
                <span>Top K</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={checklistTopK}
                  onChange={(event) =>
                    setChecklistTopK(Number(event.target.value))
                  }
                  disabled={loading}
                />
              </label>
              <DocumentFilter
                documents={documents}
                selected={selectedDocs}
                onChange={setSelectedDocs}
              />
            </div>
            <div className="form-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => void submitChecklist()}
                disabled={loading || !goal.trim()}
              >
                {loading ? "生成中…" : "生成 Checklist"}
              </button>
            </div>
          </section>

          {checklistResponse ? (
            <ChecklistResultView
              response={checklistResponse}
              onPreview={onPreview}
            />
          ) : null}
        </>
      ) : (
        <>
          <p className="notice notice-warning">
            组会总结仅基于输入记录生成，负责人和截止时间请人工复核。
          </p>
          <section className="card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">MEETING NOTES</p>
                <h2>整理组会记录</h2>
              </div>
              <span className="muted">{meetingText.length} / 20000</span>
            </div>
            <div className="form-grid">
              <label className="field">
                <span>组会标题（可选）</span>
                <input
                  value={meetingTitle}
                  maxLength={200}
                  placeholder="2026-11-07 组会"
                  onChange={(event) => setMeetingTitle(event.target.value)}
                  disabled={loading}
                />
              </label>
              <label className="field">
                <span>关注主题（可选）</span>
                <input
                  value={meetingFocus}
                  maxLength={500}
                  placeholder="实验进度与下周安排"
                  onChange={(event) => setMeetingFocus(event.target.value)}
                  disabled={loading}
                />
              </label>
            </div>
            <label className="field">
              <span>组会原始记录</span>
              <textarea
                rows={10}
                maxLength={20000}
                value={meetingText}
                placeholder={"实验进度：完成 A 组。\n\n下周计划：补做 B 组。"}
                onChange={(event) => setMeetingText(event.target.value)}
                disabled={loading}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => void submitMeeting()}
                disabled={loading || !meetingText.trim()}
              >
                {loading ? "总结中…" : "生成组会总结"}
              </button>
            </div>
          </section>
          {meetingResponse ? (
            <MeetingResultView response={meetingResponse} />
          ) : null}
        </>
      )}
    </div>
  );
}

function ChecklistResultView({
  response,
  onPreview,
}: {
  response: ToolResponse;
  onPreview: (id: string, filename: string, page: number) => void;
}) {
  if (response.status === "refused") {
    return (
      <section className="card refusal-box">
        <strong>无法生成基于知识库的 Checklist</strong>
        <p>{response.refusal_reason ?? "未检索到足够证据。"}</p>
      </section>
    );
  }
  if (!isChecklistResult(response.result)) {
    return <p className="notice notice-error">工具返回了非 checklist 结果。</p>;
  }
  return (
    <section className="card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">RESULT</p>
          <h2>{response.result.title}</h2>
        </div>
        <StatusBadge value={response.status} kind="result" />
      </div>
      <div className="checklist-list">
        {response.result.items.map((item) => (
          <article className="checklist-item" key={item.id}>
            <div className="citation-head">
              <strong>{item.content}</strong>
              <span className="tag">{categoryLabels[item.category]}</span>
              <span className={`badge priority-${item.priority}`}>
                {priorityLabels[item.priority]}优先级
              </span>
            </div>
            {item.citations.map((citation) => (
              <CitationCard
                key={citation.citation_id}
                citation={citation}
                onPreview={onPreview}
              />
            ))}
            {item.citations.length === 0 ? (
              <p className="hint">该条目没有直接引用，请人工复核。</p>
            ) : null}
          </article>
        ))}
      </div>
      {response.result.notes.length > 0 ? (
        <ul className="note-list">
          {response.result.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      <p className="hint">
        工具证据数 {response.workflow.evidence_count} · 检索数{" "}
        {response.workflow.retrieval_count}
      </p>
    </section>
  );
}

function MeetingResultView({ response }: { response: ToolResponse }) {
  if (response.status === "refused") {
    return (
      <section className="card refusal-box">
        <strong>无法生成组会总结</strong>
        <p>{response.refusal_reason ?? "输入内容不足。"}</p>
      </section>
    );
  }
  if (!isMeetingResult(response.result)) {
    return <p className="notice notice-error">工具返回了非组会总结结果。</p>;
  }
  const result = response.result;
  return (
    <section className="card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">RESULT</p>
          <h2>{result.meeting_title ?? "组会总结"}</h2>
        </div>
        <StatusBadge value={response.status} kind="result" />
      </div>
      <p className="answer-text">{result.summary}</p>
      <div className="meeting-grid">
        <section>
          <h3>已确定结论</h3>
          {result.decisions.length === 0 ? (
            <p className="hint">未提取到明确结论。</p>
          ) : (
            result.decisions.map((item) => (
              <MeetingEntry
                key={`${item.content}-${item.citations[0]?.segment_id ?? ""}`}
                title={item.content}
                citations={item.citations}
              />
            ))
          )}
        </section>
        <section>
          <h3>待办事项</h3>
          {result.action_items.length === 0 ? (
            <p className="hint">未提取到待办事项。</p>
          ) : (
            result.action_items.map((item) => (
              <MeetingEntry
                key={`${item.task}-${item.citations[0]?.segment_id ?? ""}`}
                title={item.task}
                meta={`负责人：${item.owner ?? "未明确"} · 截止：${item.deadline ?? "未明确"}`}
                citations={item.citations}
              />
            ))
          )}
        </section>
        <section>
          <h3>风险与阻塞项</h3>
          {result.risks.length === 0 ? (
            <p className="hint">未提取到风险项。</p>
          ) : (
            result.risks.map((item) => (
              <MeetingEntry
                key={`${item.content}-${item.citations[0]?.segment_id ?? ""}`}
                title={item.content}
                citations={item.citations}
              />
            ))
          )}
        </section>
        <section>
          <h3>待讨论问题</h3>
          {result.open_questions.length === 0 ? (
            <p className="hint">未提取到开放问题。</p>
          ) : (
            result.open_questions.map((item) => (
              <MeetingEntry
                key={`${item.content}-${item.citations[0]?.segment_id ?? ""}`}
                title={item.content}
                citations={item.citations}
              />
            ))
          )}
        </section>
      </div>
    </section>
  );
}

function MeetingEntry({
  title,
  meta,
  citations,
}: {
  title: string;
  meta?: string;
  citations: Array<{
    segment_id: string;
    text: string;
    char_start: number;
    char_end: number;
  }>;
}) {
  return (
    <article className="meeting-entry">
      <strong>{title}</strong>
      {meta ? <p className="muted">{meta}</p> : null}
      {citations.map((citation) => (
        <blockquote key={citation.segment_id}>
          <span className="muted">{citation.segment_id}</span>
          {citation.text}
        </blockquote>
      ))}
    </article>
  );
}
