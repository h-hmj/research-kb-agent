import { useEffect } from "react";

import { documentFileUrl } from "../api/documents";

export interface PreviewState {
  documentId: string;
  filename: string;
  page: number;
}

export function PdfPreview({
  preview,
  onClose,
}: {
  preview: PreviewState | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!preview) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview, onClose]);

  if (!preview) {
    return null;
  }
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <section className="pdf-modal">
        <header className="pdf-modal-head">
          <div>
            <strong>{preview.filename}</strong>
            <span className="muted">
              {" "}
              · 引用页码：第 {preview.page} 页
            </span>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>
            关闭
          </button>
        </header>
        <iframe
          title={`${preview.filename} PDF 预览`}
          src={documentFileUrl(preview.documentId, preview.page)}
          className="pdf-frame"
        />
        <footer className="pdf-modal-foot">
          浏览器若不支持自动跳页，请按上方标注的页码手动查看。
        </footer>
      </section>
    </div>
  );
}
