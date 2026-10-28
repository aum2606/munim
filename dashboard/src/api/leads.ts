import { authenticatedRequest as request, authenticatedStream } from "./client";
import type { Conversation, Message } from "./knowledge";
export const stages = [
  "new",
  "engaged",
  "qualified",
  "quoted",
  "negotiating",
  "won",
  "lost",
  "dormant",
] as const;
export type Stage = (typeof stages)[number];
export interface Lead {
  id: string;
  conversation_id: string;
  stage: Stage;
  stage_override: boolean;
  score: number;
  summary: string;
  tags: string[];
  category: string;
  display_estimated_value: string;
  assigned_to: string | null;
  lost_reason: string | null;
  next_followup_at: string | null;
  requirements: Record<string, unknown>;
}
export interface LeadEvent {
  id: string;
  event_type: string;
  from_value: string | null;
  to_value: string | null;
  note: string;
  actor: string;
  created_at: string;
}
export interface Followup {
  id: string;
  lead_id: string;
  kind: string;
  draft_text: string;
  status: string;
  scheduled_at: string;
  requires_template: boolean;
}
export interface Handoff {
  id: string;
  conversation_id: string;
  reason: string;
  summary: string;
  status: string;
}
export interface Draft {
  id: string;
  content: string;
  status: string;
}
export interface Policy {
  enabled: boolean;
  no_reply_days: number;
  quote_reminder_days: number;
  reengage_days: number;
}
export interface InboxSnapshot {
  conversations: Conversation[];
  handoffs: Handoff[];
  followups: Followup[];
}
const body = (value: unknown, method = "POST") => ({
  method,
  body: JSON.stringify(value),
});
export const leadsApi = {
  list: () => request<Lead[]>("/leads"),
  detail: (id: string) => request<Lead>("/leads/" + id),
  events: (id: string) => request<LeadEvent[]>("/leads/" + id + "/events"),
  patch: (
    id: string,
    value: Partial<
      Pick<
        Lead,
        | "stage"
        | "stage_override"
        | "assigned_to"
        | "lost_reason"
        | "next_followup_at"
      >
    >,
  ) => request<Lead>("/leads/" + id, body(value, "PATCH")),
  followups: () => request<Followup[]>("/followups"),
  followup: (id: string, action: "approve" | "cancel", template_id?: string) =>
    request<Followup>(
      "/followups/" + id + "/action",
      body({ action, template_id }),
    ),
  policy: () => request<Policy>("/tenant/followup-policy"),
  savePolicy: (value: Policy) =>
    request<Policy>("/tenant/followup-policy", body(value, "PUT")),
  users: () => request<{ id: string; name: string }[]>("/users"),
  handoffs: () => request<Handoff[]>("/handoffs"),
  mode: (id: string, mode: string) =>
    request<void>("/conversations/" + id + "/mode", body({ mode })),
  reply: (
    id: string,
    content: string,
    external_id: string,
    buttons?: { id: string; title: string }[],
  ) =>
    request<Message>(
      "/conversations/" + id + "/messages",
      body({ content, external_id, buttons }),
    ),
  drafts: (id: string) => request<Draft[]>("/conversations/" + id + "/drafts"),
  approveDraft: (id: string) =>
    request<Message>("/reply-drafts/" + id + "/approve", body({})),
};
export async function watchInbox(
  onSnapshot: (snapshot: InboxSnapshot) => void,
  signal: AbortSignal,
  onStatus: (connected: boolean) => void,
) {
  while (!signal.aborted) {
    try {
      const response = await authenticatedStream(
        "/conversations/stream",
        signal,
      );
      if (!response.body) throw new Error("No stream");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      onStatus(true);
      try {
        while (!signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let end: number;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const event = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            const data = event
              .split("\n")
              .find((line) => line.startsWith("data: "));
            if (data) onSnapshot(JSON.parse(data.slice(6)) as InboxSnapshot);
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (error) {
      if (signal.aborted) return;
      onStatus(false);
      void error;
    }
    if (!signal.aborted)
      await new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer);
          signal.removeEventListener("abort", finish);
          resolve();
        };
        const timer = setTimeout(finish, 2000);
        signal.addEventListener("abort", finish, { once: true });
      });
  }
}
