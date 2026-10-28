import {
  authenticatedDownload,
  authenticatedRequest as request,
} from "./client";
export interface Tenant {
  id: string;
  name: string;
  business_type: string;
  widget_public_key: string;
  widget_script_url: string;
  public_api_url: string;
  model_mode: string;
}
export interface CatalogItem {
  id: string;
  sku: string;
  name: string;
  display_price: string;
  gst_rate: number;
  unit: string;
  is_active: boolean;
}
export interface ImportPreview {
  id: string;
  headers: string[];
  mapping: Record<string, string>;
  committed: boolean;
  rows: {
    number: number;
    catalog: { sku: string; name: string } | null;
    display_price: string | null;
    errors: string[];
  }[];
}
export interface Document {
  id: string;
  title: string;
  source_type: string;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
}
export interface KnowledgeGap {
  id: string;
  question: string;
  occurrences: number;
  status: "open" | "answered" | "ignored";
  answer_text: string | null;
}
export interface Conversation {
  id: string;
  channel: string;
  mode: string;
  status: string;
  last_customer_msg_at: string | null;
  last_business_msg_at: string | null;
}
export interface Message {
  id: string;
  conversation_id: string;
  direction: "in" | "out";
  content: string;
  created_at: string;
  attachments: {
    citations?: string[];
    media_id?: string;
    filename?: string;
    kind?: string;
  }[];
}
export interface AgentRun {
  id: string;
  message_id: string | null;
  agent: string;
  model: string;
  status: string;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  tool_calls: Record<string, unknown>[];
  error: string | null;
}
async function upload<T>(path: string, file: File) {
  const form = new FormData();
  form.set("file", file);
  return request<T>(path, { method: "POST", body: form });
}
export const knowledgeApi = {
  tenant: () => request<Tenant>("/tenant"),
  catalog: () => request<CatalogItem[]>("/catalog/items"),
  template: () => authenticatedDownload("/catalog/template.xlsx"),
  import: (file: File) => upload<ImportPreview>("/catalog/import", file),
  preview: (id: string, mapping: Record<string, string>) =>
    request<ImportPreview>(`/catalog/import/${id}/preview`, {
      method: "POST",
      body: JSON.stringify({ mapping }),
    }),
  commit: (id: string, mapping: Record<string, string>) =>
    request<ImportPreview>(`/catalog/import/${id}/commit`, {
      method: "POST",
      body: JSON.stringify({ mapping }),
    }),
  documents: () => request<Document[]>("/documents"),
  upload: (file: File) => upload<Document>("/documents", file),
  retry: (id: string) =>
    request<Document>(`/documents/${id}/retry`, { method: "POST" }),
  faq: (question: string, answer: string) =>
    request<Document>("/faqs", {
      method: "POST",
      body: JSON.stringify({ question, answer }),
    }),
  gaps: () => request<KnowledgeGap[]>("/knowledge-gaps"),
  answerGap: (id: string, answer: string) =>
    request<KnowledgeGap>(`/knowledge-gaps/${id}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  conversations: () => request<Conversation[]>("/conversations"),
  messages: (id: string) => request<Message[]>(`/conversations/${id}/messages`),
  traces: (id: string) =>
    request<AgentRun[]>(`/agent-runs?message_id=${encodeURIComponent(id)}`),
};
