import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteDocument,
  getDocument,
  indexDocument,
  listDocuments,
  uploadDocument,
} from "../api/documents";
import { getLastRequestId, userMessage } from "../api/client";
import type { DocumentDetail, DocumentSummary } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, formatFileSize } from "../lib/format";

export function DocumentsPage({
  onPreview,
}: {
  onPreview: (id: string, filename: string, page: number) => void;
}) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await listDocuments();
      setDocuments(payload.items);
      setError(null);
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleUpload = async () => {
    if (!file || uploading) {
      return;
    }
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const created = await uploadDocument(file);
      setNotice(`已上传：${created.original_filename}`);
      setFile(null);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      await refresh();
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setUploading(false);
    }
  };

  const handleIndex = async (document: DocumentSummary) => {
    setBusyId(document.id);
    setError(null);
    setNotice(null);
    try {
      const response = await indexDocument(document.id);
      setNotice(
        `索引完成：${response.chunk_count} 个 chunk，维度 ${response.embedding_dimension}`,
      );
      await refresh();
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (document: DocumentSummary) => {
    const confirmed = window.confirm(
      `确定删除「${document.original_filename}」吗？\n\n将同时删除 PDF、元数据、chunk 和索引记录，且不可恢复。`,
    );
    if (!confirmed) {
      return;
    }
    setBusyId(document.id);
    setError(null);
    setNotice(null);
    try {
      await deleteDocument(document.id);
      if (detail?.id === document.id) {
        setDetail(null);
      }
      setNotice(`已删除：${document.original_filename}`);
      await refresh();
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setBusyId(null);
    }
  };

  const handleDetail = async (document: DocumentSummary) => {
    setBusyId(document.id);
    setError(null);
    try {
      setDetail(await getDocument(document.id));
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">DOCUMENT LIBRARY</p>
          <h1>文档库</h1>
          <p className="lede">上传 PDF，按页解析并建立本地 FAISS 索引。</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void refresh()}>
          刷新列表
        </button>
      </header>

      <section className="card upload-card">
        <div>
          <p className="eyebrow">01 / UPLOAD</p>
          <h2>上传 PDF</h2>
          <p className="muted">只接受 PDF，上传后不会自动索引。</p>
        </div>
        <div className="upload-row">
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="primary-button"
            disabled={!file || uploading}
            onClick={() => void handleUpload()}
          >
            {uploading ? "上传中…" : "上传文档"}
          </button>
        </div>
        {file ? (
          <p className="hint">
            已选择：{file.name} · {formatFileSize(file.size)}
          </p>
        ) : null}
      </section>

      {error ? (
        <p className="notice notice-error">
          {error}
          {getLastRequestId() ? (
            <small> · request_id: {getLastRequestId()}</small>
          ) : null}
        </p>
      ) : null}
      {notice ? <p className="notice notice-success">{notice}</p> : null}

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">02 / LIBRARY</p>
            <h2>文档列表</h2>
          </div>
          <span className="muted">{documents.length} 个文档</span>
        </div>
        {loading ? <p className="empty-state">正在加载文档…</p> : null}
        {!loading && documents.length === 0 ? (
          <p className="empty-state">还没有文档，先上传一份 PDF。</p>
        ) : null}
        {documents.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件名</th>
                  <th>页数</th>
                  <th>大小</th>
                  <th>上传时间</th>
                  <th>处理</th>
                  <th>索引</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((document) => (
                  <tr key={document.id}>
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => void handleDetail(document)}
                      >
                        {document.original_filename}
                      </button>
                    </td>
                    <td>{document.page_count}</td>
                    <td>{formatFileSize(document.file_size)}</td>
                    <td>{formatDateTime(document.created_at)}</td>
                    <td>
                      <StatusBadge value={document.status} />
                    </td>
                    <td>
                      <StatusBadge value={document.index_status} kind="index" />
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          type="button"
                          className="text-button"
                          disabled={busyId === document.id}
                          onClick={() => void handleIndex(document)}
                        >
                          {busyId === document.id
                            ? "正在建立索引…"
                            : document.index_status === "indexed"
                              ? "重建索引"
                              : "建立索引"}
                        </button>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() =>
                            onPreview(
                              document.id,
                              document.original_filename,
                              1,
                            )
                          }
                        >
                          预览 PDF
                        </button>
                        <button
                          type="button"
                          className="text-button danger-text"
                          disabled={busyId === document.id}
                          onClick={() => void handleDelete(document)}
                        >
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {detail ? (
        <section className="card detail-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">DOCUMENT DETAIL</p>
              <h2>{detail.original_filename}</h2>
            </div>
            <button
              type="button"
              className="icon-button"
              onClick={() => setDetail(null)}
            >
              关闭
            </button>
          </div>
          <dl className="detail-grid">
            <div>
              <dt>页数</dt>
              <dd>{detail.page_count}</dd>
            </div>
            <div>
              <dt>文件大小</dt>
              <dd>{formatFileSize(detail.file_size)}</dd>
            </div>
            <div>
              <dt>上传时间</dt>
              <dd>{formatDateTime(detail.created_at)}</dd>
            </div>
            <div>
              <dt>索引状态</dt>
              <dd>
                <StatusBadge value={detail.index_status} kind="index" />
              </dd>
            </div>
          </dl>
          <details className="document-id">
            <summary>文档 ID</summary>
            <code>{detail.id}</code>
          </details>
          <h3>逐页统计</h3>
          <div className="page-stats">
            {detail.pages.map((page) => (
              <div key={page.page_number} className="page-stat">
                <strong>第 {page.page_number} 页</strong>
                <span>{page.character_count} 字符</span>
                <button
                  type="button"
                  className="text-button"
                  onClick={() =>
                    onPreview(
                      detail.id,
                      detail.original_filename,
                      page.page_number,
                    )
                  }
                >
                  查看此页
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
