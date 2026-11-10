import type { DocumentStatus, IndexStatus } from "../api/types";

const labels: Record<string, string> = {
  processed: "已处理",
  failed: "处理失败",
  not_indexed: "未索引",
  indexed: "已索引",
  indexing: "索引中",
  answered: "已回答",
  refused: "拒答",
  success: "成功",
  error: "错误",
  running: "运行中",
  retrieval: "仅检索",
  qa: "基础 QA",
  agent: "Agent",
  compare: "对比",
};

export function StatusBadge({
  value,
  kind,
}: {
  value: DocumentStatus | IndexStatus | string;
  kind?: "status" | "index" | "result";
}) {
  const tone =
    value === "failed" || value === "error"
      ? "danger"
      : value === "indexed" || value === "success" || value === "answered"
        ? "success"
        : value === "refused"
          ? "warning"
          : value === "not_indexed"
            ? "muted"
            : "info";
  return (
    <span className={`badge badge-${tone} badge-${kind ?? "status"}`}>
      {labels[value] ?? value}
    </span>
  );
}
