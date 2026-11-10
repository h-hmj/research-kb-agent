import { useState } from "react";

import type { Citation } from "../api/types";

export function CitationCard({
  citation,
  onPreview,
}: {
  citation: Citation;
  onPreview: (documentId: string, filename: string, page: number) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <article className="citation-card">
      <div className="citation-head">
        <button
          type="button"
          className="link-button"
          onClick={() =>
            onPreview(
              citation.document_id,
              citation.original_filename,
              citation.page_number,
            )
          }
        >
          {citation.original_filename} · 第 {citation.page_number} 页
        </button>
        <span className="muted">相似度 {citation.score.toFixed(3)}</span>
      </div>
      <p className={`citation-text ${open ? "expanded" : ""}`}>
        {citation.text}
      </p>
      <div className="row-actions">
        <button
          type="button"
          className="text-button"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "收起原文" : "展开原文"}
        </button>
        <button
          type="button"
          className="text-button"
          onClick={() =>
            onPreview(
              citation.document_id,
              citation.original_filename,
              citation.page_number,
            )
          }
        >
          查看原文
        </button>
      </div>
    </article>
  );
}
