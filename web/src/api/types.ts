export type ViewName =
  | "dashboard"
  | "documents"
  | "agent"
  | "tools"
  | "evaluations"
  | "system";

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export type DocumentStatus = "processed" | "failed";
export type IndexStatus = "not_indexed" | "indexed" | "failed";

export interface DocumentSummary {
  id: string;
  original_filename: string;
  stored_filename: string;
  file_size: number;
  page_count: number;
  created_at: string;
  status: DocumentStatus;
  index_status: IndexStatus;
}

export interface DocumentPage {
  page_number: number;
  text: string;
  character_count: number;
}

export interface DocumentDetail extends DocumentSummary {
  pages: DocumentPage[];
}

export interface DocumentListResponse {
  items: DocumentSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface RetrievalResult {
  chunk_id: string;
  document_id: string;
  original_filename: string;
  page_number: number;
  chunk_index: number;
  text: string;
  char_start: number;
  char_end: number;
  score: number;
}

export interface Citation {
  citation_id: string;
  chunk_id: string;
  document_id: string;
  original_filename: string;
  page_number: number;
  chunk_index: number;
  text: string;
  char_start: number;
  char_end: number;
  score: number;
}

export interface QARetrieval {
  query: string;
  retrieved_count: number;
  evidence_count: number;
  top_k: number;
}

export interface QAResponse {
  status: "answered" | "refused";
  answer: string;
  citations: Citation[];
  retrieval: QARetrieval;
  refusal_reason: string | null;
}

export interface AgentWorkflow {
  original_question: string;
  final_query: string;
  rewrite_attempted: boolean;
  rewrite_count: number;
  rewrite_changed: boolean;
  steps: string[];
  initial_retrieval_count: number;
  final_retrieval_count: number;
  evidence_count: number;
}

export interface AgentMetrics {
  total_duration_ms: number;
  retrieval_duration_ms: number;
  llm_duration_ms: number;
}

export interface WorkflowEventData {
  request_id: string;
  step: string;
  message: string;
}

export interface TokenEventData {
  request_id: string;
  content: string;
}

export interface CitationsEventData {
  request_id: string;
  citations: Citation[];
}

export interface FinalEventData {
  request_id: string;
  status: "answered" | "refused";
  refusal_reason: string | null;
  workflow: AgentWorkflow;
  metrics: AgentMetrics;
}

export interface ErrorEventData {
  request_id: string;
  code: string;
  message: string;
}

export type AgentStreamEvent =
  | { event: "workflow"; data: WorkflowEventData }
  | { event: "token"; data: TokenEventData }
  | { event: "citations"; data: CitationsEventData }
  | { event: "final"; data: FinalEventData }
  | { event: "error"; data: ErrorEventData };

export interface ToolWorkflow {
  steps: string[];
  llm_called: boolean;
  retrieval_count: number;
  evidence_count: number;
}

export interface ChecklistItem {
  id: string;
  category: "preparation" | "operation" | "recording" | "review";
  content: string;
  priority: "high" | "medium" | "low";
  citations: Citation[];
}

export interface ChecklistResult {
  title: string;
  items: ChecklistItem[];
  notes: string[];
}

export interface ChecklistRefusalResult {
  checklist: [];
}

export interface MeetingCitation {
  segment_id: string;
  text: string;
  char_start: number;
  char_end: number;
}

export interface MeetingDecision {
  content: string;
  citations: MeetingCitation[];
}

export interface MeetingActionItem {
  task: string;
  owner: string | null;
  deadline: string | null;
  citations: MeetingCitation[];
}

export interface MeetingRisk {
  content: string;
  citations: MeetingCitation[];
}

export interface MeetingQuestion {
  content: string;
  citations: MeetingCitation[];
}

export interface MeetingSummaryResult {
  meeting_title: string | null;
  summary: string;
  decisions: MeetingDecision[];
  action_items: MeetingActionItem[];
  risks: MeetingRisk[];
  open_questions: MeetingQuestion[];
}

export interface SearchToolResult {
  query: string;
  results: RetrievalResult[];
}

export type ToolResult =
  | ChecklistResult
  | ChecklistRefusalResult
  | MeetingSummaryResult
  | SearchToolResult;

export interface ToolResponse {
  status: "success" | "refused";
  tool_name:
    | "search_knowledge_base"
    | "generate_experiment_checklist"
    | "summarize_meeting_notes";
  result: ToolResult;
  workflow: ToolWorkflow;
  refusal_reason: string | null;
}

export interface MetricBlock {
  retrieval: {
    recall_at_k: number | null;
    mrr_at_k: number | null;
  };
  citation: {
    precision: number | null;
    recall: number | null;
  };
  refusal: {
    accuracy: number | null;
    hallucinated_answer_rate: number | null;
    false_refusal_rate: number | null;
  };
  answer: {
    keyword_hit_rate: number | null;
    keyword_evaluated_cases: number;
  };
  agent: {
    rewrite_rate: number | null;
    retry_success_rate: number | null;
  };
}

export type EvaluationMode = "retrieval" | "qa" | "agent" | "compare";

export interface EvaluationRunResponse {
  run_id: string;
  mode: EvaluationMode;
  summary: {
    status: string;
    metrics: MetricBlock | Record<"qa" | "agent", MetricBlock>;
    error_case_count: number;
  };
  report_available: boolean;
}

export interface EvaluationListItem {
  run_id: string;
  created_at: string;
  mode: string;
  status: string;
  dataset_name: string;
  total_cases: number;
  answerable_cases: number;
  unanswerable_cases: number;
  error_case_count: number;
  metrics: MetricBlock | Record<"qa" | "agent", MetricBlock>;
}

export interface CaseResult {
  case_id: string;
  expected_answerable: boolean;
  actual_status: string;
  retrieval_hit: boolean | null;
  first_relevant_rank: number | null;
  citation_correct_count: number;
  citation_total_count: number;
  expected_source_count: number;
  matched_expected_source_count: number;
  keyword_hit: boolean | null;
  rewrite_attempted: boolean;
  retry_success: boolean | null;
  error_code: string | null;
}

export interface EvaluationReport {
  run_id: string;
  created_at: string;
  status: string;
  mode: EvaluationMode;
  dataset: {
    name: string;
    sha256: string;
    total_cases: number;
    answerable_cases: number;
    unanswerable_cases: number;
  };
  configuration: Record<string, string | number | boolean>;
  metrics: MetricBlock | Record<"qa" | "agent", MetricBlock>;
  case_results: CaseResult[] | Record<string, CaseResult[]>;
  error_case_count: number;
  limitations: string[];
}

export interface AgentStreamMetrics {
  requests_total: number;
  answered_total: number;
  refused_total: number;
  errors_total: number;
  average_duration_ms: number;
}

export interface MetricsSnapshot {
  requests_total: number;
  requests_by_path: Record<string, number>;
  responses_by_status: Record<string, number>;
  agent_stream: AgentStreamMetrics;
  tool_requests_total: number;
  llm: {
    calls_total: number;
    stream_calls_total: number;
    errors_total: number;
  };
  embedding_errors_total: number;
  total_request_duration_ms: number;
  total_agent_stream_duration_ms: number;
  generated_at: string;
}
