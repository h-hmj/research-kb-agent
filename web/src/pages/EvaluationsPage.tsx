import { useCallback, useEffect, useState } from "react";

import { userMessage } from "../api/client";
import {
  getEvaluation,
  listEvaluations,
  runEvaluation,
} from "../api/evaluations";
import type {
  EvaluationListItem,
  EvaluationMode,
  EvaluationReport,
  MetricBlock,
} from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { percent } from "../lib/format";

const MODES: Array<{ value: EvaluationMode; label: string }> = [
  { value: "retrieval", label: "retrieval · 仅检索" },
  { value: "qa", label: "qa · 基础问答" },
  { value: "agent", label: "agent · LangGraph" },
  { value: "compare", label: "compare · QA vs Agent" },
];

function isCompareMetrics(
  metrics: MetricBlock | Record<"qa" | "agent", MetricBlock>,
): metrics is Record<"qa" | "agent", MetricBlock> {
  return "qa" in metrics && "agent" in metrics;
}

function MetricsTable({ block }: { block: MetricBlock }) {
  const rows: Array<[string, string]> = [
    ["Recall@K", percent(block.retrieval.recall_at_k)],
    ["MRR@K", percent(block.retrieval.mrr_at_k)],
    ["Citation Precision", percent(block.citation.precision)],
    ["Citation Recall", percent(block.citation.recall)],
    ["Refusal Accuracy", percent(block.refusal.accuracy)],
    [
      "Hallucinated Answer Rate",
      percent(block.refusal.hallucinated_answer_rate),
    ],
    ["False Refusal Rate", percent(block.refusal.false_refusal_rate)],
    ["Keyword Hit Rate（弱）", percent(block.answer.keyword_hit_rate)],
    ["Agent Rewrite Rate", percent(block.agent.rewrite_rate)],
    ["Agent Retry Success", percent(block.agent.retry_success_rate)],
  ];
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>指标</th>
            <th>值</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EvaluationsPage() {
  const [datasetName, setDatasetName] = useState("sample_eval.jsonl");
  const [mode, setMode] = useState<EvaluationMode>("compare");
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [history, setHistory] = useState<EvaluationListItem[]>([]);

  const refreshHistory = useCallback(async () => {
    try {
      setHistory(await listEvaluations());
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  const run = async () => {
    if (!datasetName.trim() || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const response = await runEvaluation(datasetName.trim(), mode, topK);
      setReport(await getEvaluation(response.run_id));
      await refreshHistory();
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  const loadReport = async (runId: string) => {
    setLoading(true);
    setError(null);
    try {
      setReport(await getEvaluation(runId));
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
          <p className="eyebrow">REPRODUCIBLE EVALUATION</p>
          <h1>评测报告</h1>
          <p className="lede">
            用人工标注题集统计检索、引用、拒答和 Agent 工作流指标。
          </p>
        </div>
        <span className="badge badge-info">本地小规模评测</span>
      </header>

      <p className="notice notice-warning">
        关键词命中率不等于真实回答准确率；结果只对当前数据集、知识库、模型与配置有效。
        小样例评测不能代表通用模型能力。
      </p>

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">RUN</p>
            <h2>运行评测</h2>
          </div>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>数据集名称</span>
            <input
              value={datasetName}
              placeholder="sample_eval.jsonl"
              onChange={(event) => setDatasetName(event.target.value)}
              disabled={loading}
            />
            <small className="hint">必须是 EVAL_DATASET_DIR 下的 JSONL 文件。</small>
          </label>
          <label className="field">
            <span>模式</span>
            <select
              value={mode}
              onChange={(event) =>
                setMode(event.target.value as EvaluationMode)
              }
              disabled={loading}
            >
              {MODES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Top K</span>
            <input
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value))}
              disabled={loading}
            />
          </label>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="primary-button"
            onClick={() => void run()}
            disabled={loading || !datasetName.trim()}
          >
            {loading ? "评测运行中…" : "开始评测"}
          </button>
        </div>
        {error ? <p className="notice notice-error">{error}</p> : null}
      </section>

      {report ? (
        <section className="card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">REPORT</p>
              <h2>{report.dataset.name}</h2>
              <p className="muted">
                {report.run_id} · {report.mode} · {report.created_at}
              </p>
            </div>
            <StatusBadge value={report.status} kind="result" />
          </div>
          <div className="stat-row">
            <div>
              <span>样例数</span>
              <strong>{report.dataset.total_cases}</strong>
            </div>
            <div>
              <span>answerable</span>
              <strong>{report.dataset.answerable_cases}</strong>
            </div>
            <div>
              <span>unanswerable</span>
              <strong>{report.dataset.unanswerable_cases}</strong>
            </div>
            <div>
              <span>内部错误</span>
              <strong>{report.error_case_count}</strong>
            </div>
          </div>
          {isCompareMetrics(report.metrics) ? (
            <div className="compare-grid">
              <section>
                <h3>基础 QA</h3>
                <MetricsTable block={report.metrics.qa} />
              </section>
              <section>
                <h3>LangGraph Agent</h3>
                <MetricsTable block={report.metrics.agent} />
              </section>
            </div>
          ) : (
            <MetricsTable block={report.metrics} />
          )}
          <details className="document-id">
            <summary>配置快照</summary>
            <pre>{JSON.stringify(report.configuration, null, 2)}</pre>
          </details>
          <ul className="note-list">
            {report.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">HISTORY</p>
            <h2>历史报告</h2>
          </div>
          <span className="muted">{history.length} 次运行</span>
        </div>
        {history.length === 0 ? (
          <p className="empty-state">还没有评测报告。</p>
        ) : (
          <div className="history-list">
            {history.map((item) => (
              <button
                type="button"
                className="history-item"
                key={item.run_id}
                onClick={() => void loadReport(item.run_id)}
              >
                <span>{item.dataset_name}</span>
                <strong>{item.mode}</strong>
                <small>
                  {item.total_cases} 题 · 错误 {item.error_case_count}
                </small>
                <code>{item.run_id}</code>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
