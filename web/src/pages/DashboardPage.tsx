import { useEffect, useState } from "react";

import { userMessage } from "../api/client";
import { getHealth } from "../api/observability";
import type { HealthResponse, ViewName } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";

const CAPABILITIES = [
  {
    title: "页码级引用",
    text: "回答只带后端返回的文档、页码和原文片段，引用可回到 PDF。",
  },
  {
    title: "无证据拒答",
    text: "检索证据不足时不调用回答模型，明确说明无法回答。",
  },
  {
    title: "LangGraph 二次检索",
    text: "初次检索不足时最多改写一次、二次检索一次，不无限循环。",
  },
  {
    title: "本地评测指标",
    text: "用人工标注题集统计检索、引用、拒答和 Agent 改写效果。",
  },
];

const FLOW = [
  "上传 PDF",
  "文本解析与分块",
  "本地向量检索",
  "LangGraph 工作流",
  "回答 / 拒答 / 引用",
];

export function DashboardPage({
  onNavigate,
}: {
  onNavigate: (view: ViewName) => void;
}) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getHealth()
      .then((payload) => {
        if (active) {
          setHealth(payload);
          setHealthError(null);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setHealthError(userMessage(error));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">LOCAL RESEARCH ASSISTANT</p>
          <h1>科研知识库与实验助理 Agent</h1>
          <p className="lede">
            面向论文、实验记录和组会材料的可追溯本地知识库 Agent。
          </p>
        </div>
        <div className="health-pill">
          <span
            className={`health-dot ${health ? "online" : healthError ? "offline" : ""}`}
          />
          {health ? "后端服务正常" : healthError ? "后端服务不可用" : "正在检查后端"}
          {health ? <small>v{health.version}</small> : null}
        </div>
      </header>

      <section className="capability-grid">
        {CAPABILITIES.map((item, index) => (
          <article className="card capability-card" key={item.title}>
            <span className="card-index">0{index + 1}</span>
            <h2>{item.title}</h2>
            <p>{item.text}</p>
          </article>
        ))}
      </section>

      <section className="card flow-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">WORKFLOW</p>
            <h2>从资料到可追溯回答</h2>
          </div>
          <StatusBadge value="success" kind="result" />
        </div>
        <div className="flow">
          {FLOW.map((step, index) => (
            <div className="flow-step" key={step}>
              <span>{index + 1}</span>
              <strong>{step}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="quick-grid">
        <button
          type="button"
          className="quick-card"
          onClick={() => onNavigate("documents")}
        >
          <span className="quick-kicker">01 / INGEST</span>
          <strong>上传文档</strong>
          <small>PDF 上传、解析和本地索引</small>
        </button>
        <button
          type="button"
          className="quick-card"
          onClick={() => onNavigate("agent")}
        >
          <span className="quick-kicker">02 / ASK</span>
          <strong>开始 Agent 问答</strong>
          <small>观察检索、改写、流式回答和引用</small>
        </button>
        <button
          type="button"
          className="quick-card"
          onClick={() => onNavigate("evaluations")}
        >
          <span className="quick-kicker">03 / MEASURE</span>
          <strong>查看评测报告</strong>
          <small>Recall、引用、拒答和对比指标</small>
        </button>
      </section>

      {healthError ? (
        <p className="notice notice-warning">
          健康检查失败：{healthError}。界面仍可浏览，但 API 操作可能不可用。
        </p>
      ) : null}
    </div>
  );
}
