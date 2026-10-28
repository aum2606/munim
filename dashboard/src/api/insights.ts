import { authenticatedRequest as request } from "./client";
export type Cell = string | number | null;
export type Period = "7d" | "30d" | "90d" | "this_week" | "this_month";
export interface AnalyticsResult {
  columns: string[];
  rows: Record<string, Cell>[];
  total: number;
  truncated: boolean;
}
export interface ChartSpec {
  kind: "bar" | "line";
  title: string;
  x_key: string;
  y_key: string;
  rows: Record<string, Cell>[];
}
export interface InsightAnswer {
  text: string;
  table: Record<string, Cell>[] | null;
  columns: string[];
  chart_spec: ChartSpec | null;
  suggested_actions: string[];
  tool: string | null;
  period_start: string;
  period_end: string;
  total: number;
  truncated: boolean;
}
export interface Overview {
  period_start: string;
  period_end: string;
  enquiries: number;
  inbound_messages: number;
  closed_conversations: number;
  ai_resolved_conversations: number;
  ai_resolution_rate_pct: number | null;
  first_response: AnalyticsResult;
  trend: AnalyticsResult;
  top_items: AnalyticsResult;
  intent_mix: AnalyticsResult;
  funnel: AnalyticsResult;
  channels: AnalyticsResult;
  open_gaps: number;
}
export interface Digest {
  id: string;
  week_start: string;
  period_end: string;
  answer: InsightAnswer;
}
export const insightsApi = {
  overview: (period: Period) =>
    request<Overview>(`/analytics/overview?period=${period}`),
  ask: (question: string) =>
    request<InsightAnswer>("/insights/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  digest: () => request<Digest | null>("/insights/digest/latest"),
};
