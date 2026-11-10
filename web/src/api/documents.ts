import { apiRequest, apiUrl } from "./client";
import type {
  DocumentDetail,
  DocumentListResponse,
  DocumentSummary,
} from "./types";

const DOCUMENTS = "/api/v1/documents";

export interface IndexDocumentResponse {
  document_id: string;
  status: string;
  page_count: number;
  chunk_count: number;
  embedding_dimension: number;
}

export function listDocuments(): Promise<DocumentListResponse> {
  return apiRequest<DocumentListResponse>(`${DOCUMENTS}?page=1&page_size=100`);
}

export function getDocument(documentId: string): Promise<DocumentDetail> {
  return apiRequest<DocumentDetail>(`${DOCUMENTS}/${documentId}`);
}

export function uploadDocument(file: File): Promise<DocumentDetail> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<DocumentDetail>(DOCUMENTS, {
    method: "POST",
    body,
  });
}

export function indexDocument(
  documentId: string,
): Promise<IndexDocumentResponse> {
  return apiRequest<IndexDocumentResponse>(`${DOCUMENTS}/${documentId}/index`, {
    method: "POST",
  });
}

export function deleteDocument(documentId: string): Promise<void> {
  return apiRequest<void>(`${DOCUMENTS}/${documentId}`, {
    method: "DELETE",
  });
}

export function documentFileUrl(documentId: string, page?: number): string {
  const base = apiUrl(`${DOCUMENTS}/${documentId}/file`);
  return page ? `${base}#page=${page}` : base;
}

export function indexedDocuments(
  documents: DocumentSummary[],
): DocumentSummary[] {
  return documents.filter((item) => item.index_status === "indexed");
}
