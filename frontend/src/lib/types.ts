// lib/types.ts — Shared TypeScript types matching backend schemas

export type VerificationStatus = 'pending' | 'verified' | 'rejected';
export type PaperRole = 'literature' | 'project';
export type ComparisonResult = 'matches_existing' | 'partial_overlap' | 'not_found_in_corpus';

export interface UploadedFile {
  id: number;
  filename: string;
  status: string;
}

export interface UploadResponse {
  paper_ids: number[];
  filenames: string[];
  message: string;
}

export interface ClarificationRequest {
  id: number;
  paper_id: number;
  field_name: string;
  prompt: string;
  user_response: string | null;
  resolved: boolean;
}

export interface UploadStatus {
  literature_count: number;
  project_count: number;
  max_literature: number;
  ready_to_run: boolean;
  literature_files: UploadedFile[];
}

export interface PipelineEvent {
  stage?: number;
  total_stages?: number;
  message?: string;
  timestamp?: string;
  done?: boolean;
  error?: string;
  clarifications_needed?: number;
  keepalive?: boolean;
}

export interface GeneratedSentence {
  id: number;
  section: string;
  text: string;
  cited_claim_ids: number[];
  status: VerificationStatus;
  rejection_reason: string | null;
}

export interface BibEntry {
  paper_id: number;
  title: string;
  authors: string[];
  year: number | null;
}

export interface TransparencyReport {
  papers_analyzed: number;
  claims_extracted: number;
  sentences_generated: number;
  sentences_verified: number;
  sentences_rejected: number;
  open_clarifications: number;
  rejected_details: {
    id: number;
    section: string;
    text: string;
    rejection_reason: string;
    cited_claim_ids: number[];
  }[];
  llm_usage: {
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_cost_usd: number;
    by_stage: Record<string, { model: string; prompt_tokens: number; completion_tokens: number; cost_usd: number }>;
  };
}

export interface PaperPreviewData {
  markdown: string;
  bibliography: BibEntry[];
  transparency: TransparencyReport;
  section_count: number;
  sentence_count: number;
}

export type AppStage =
  | 'upload'
  | 'running'
  | 'clarification'
  | 'complete'
  | 'error';
