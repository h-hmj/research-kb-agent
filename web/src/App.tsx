import { useState } from "react";

import { PdfPreview, type PreviewState } from "./components/PdfPreview";
import { AgentPage } from "./pages/AgentPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { EvaluationsPage } from "./pages/EvaluationsPage";
import { SystemPage } from "./pages/SystemPage";
import { ToolsPage } from "./pages/ToolsPage";
import type { ViewName } from "./api/types";

const NAV: Array<{ id: ViewName; label: string; hint: string }> = [
  { id: "dashboard", label: "总览", hint: "能力与流程" },
  { id: "documents", label: "文档库", hint: "上传、索引、预览" },
  { id: "agent", label: "Agent 问答", hint: "检索与流式回答" },
  { id: "tools", label: "科研工具", hint: "checklist / 组会" },
  { id: "evaluations", label: "评测", hint: "可复现指标" },
  { id: "system", label: "系统状态", hint: "健康与指标" },
];

export default function App() {
  const [view, setView] = useState<ViewName>("dashboard");
  const [preview, setPreview] = useState<PreviewState | null>(null);

  const openPreview = (
    documentId: string,
    filename: string,
    page: number,
  ) => {
    setPreview({ documentId, filename, page });
  };

  const page = (() => {
    switch (view) {
      case "documents":
        return <DocumentsPage onPreview={openPreview} />;
      case "agent":
        return <AgentPage onPreview={openPreview} />;
      case "tools":
        return <ToolsPage onPreview={openPreview} />;
      case "evaluations":
        return <EvaluationsPage />;
      case "system":
        return <SystemPage />;
      default:
        return <DashboardPage onNavigate={setView} />;
    }
  })();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">RA</span>
          <div>
            <strong>科研知识库</strong>
            <small>Research Agent</small>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${view === item.id ? "active" : ""}`}
              onClick={() => setView(item.id)}
            >
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="dot" />
          本地演示环境
          <small>无登录 · 无云端依赖</small>
        </div>
      </aside>
      <main className="main-content">{page}</main>
      <PdfPreview preview={preview} onClose={() => setPreview(null)} />
    </div>
  );
}
