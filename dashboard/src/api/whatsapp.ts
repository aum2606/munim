import {
  authenticatedDownload,
  authenticatedRequest as request,
} from "./client";
export interface WhatsAppAccount {
  id: string;
  external_id: string;
  business_account_id: string;
  status: "active" | "disabled";
}
export interface WhatsAppTemplate {
  id: string;
  account_id: string;
  name: string;
  language: string;
  status: string;
  body_text: string;
  usable: boolean;
}
export interface WhatsAppConsent {
  opted_in_at: string | null;
  opted_out: boolean;
  consent_note: string;
  freeform_allowed: boolean;
}
export type DeliveryState =
  | "queued"
  | "retry"
  | "sending"
  | "sent"
  | "delivered"
  | "read"
  | "failed"
  | "uncertain"
  | "blocked";
export interface WhatsAppDelivery {
  id: string;
  message_id: string;
  conversation_id: string | null;
  content_preview: string;
  status: DeliveryState;
  attempts: number;
  last_error: string | null;
  provider_message_id: string | null;
  next_attempt_at: string;
}
export interface WhatsAppSetup {
  callback_url: string;
  encryption_ready: boolean;
  webhook_ready: boolean;
  api_version_ready: boolean;
}
export interface WhatsAppFollowupOptions {
  conversation_id: string;
  consent: WhatsAppConsent;
  templates: WhatsAppTemplate[];
}
const body = (value: unknown, method = "POST") => ({
  method,
  body: JSON.stringify(value),
});
export const whatsappApi = {
  media: (conversationId: string, messageId: string, mediaId: string) =>
    authenticatedDownload(
      "/conversations/" +
        conversationId +
        "/messages/" +
        messageId +
        "/media/" +
        encodeURIComponent(mediaId),
    ),
  accounts: () => request<WhatsAppAccount[]>("/channels/whatsapp"),
  setup: () => request<WhatsAppSetup>("/channels/whatsapp/setup"),
  connect: (value: {
    phone_number_id: string;
    business_account_id: string;
    access_token: string;
  }) => request<WhatsAppAccount>("/channels/whatsapp", body(value)),
  change: (id: string, status: "active" | "disabled") =>
    request<WhatsAppAccount>(
      "/channels/whatsapp/" + id,
      body({ status }, "PATCH"),
    ),
  templates: (id: string) =>
    request<WhatsAppTemplate[]>("/channels/whatsapp/" + id + "/templates"),
  sync: (id: string) =>
    request<WhatsAppTemplate[]>(
      "/channels/whatsapp/" + id + "/templates/sync",
      body({}),
    ),
  deliveries: () =>
    request<WhatsAppDelivery[]>("/channels/whatsapp/deliveries"),
  resolve: (
    id: string,
    value: { confirmed_not_sent?: boolean; provider_message_id?: string },
  ) =>
    request<WhatsAppDelivery>(
      "/channels/whatsapp/deliveries/" + id + "/resolve",
      body(value),
    ),
  consent: (id: string) =>
    request<WhatsAppConsent>("/conversations/" + id + "/whatsapp-consent"),
  saveConsent: (id: string, value: { opted_in: boolean; note: string }) =>
    request<WhatsAppConsent>(
      "/conversations/" + id + "/whatsapp-consent",
      body(value, "PUT"),
    ),
  followupOptions: (id: string) =>
    request<WhatsAppFollowupOptions>("/followups/" + id + "/whatsapp-options"),
};
