export interface Evidence {
  id: string;
  document_id: string;
  title: string;
  filename: string;
  text: string;
  page: number | null;
  location: string;
  heading?: string;
  kind?: string;
  bbox?: unknown[];
  source_metadata?: Record<string, string | number | null>;
}
export interface DocumentInfo {
  id: string;
  title: string;
  filename: string;
  kind: string;
  pages: number;
  chunk_count: number;
  metadata: Record<string, string | number | null>;
  active: number;
  parser: string;
  series_id: string;
  predecessor: string | null;
  chunks: Evidence[];
  warnings: string[];
}
export interface Citation {
  evidence_id: string;
  quote: string;
}
export interface Answer {
  status: string;
  blocks: { text: string; citations: Citation[] }[];
  evidence: Evidence[];
  mode: string;
  warnings: string[];
}
export interface Summary {
  documents: number;
  chunks: number;
  pending: number;
}
