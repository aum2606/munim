import {
  authenticatedRequest as request,
  authenticatedDownload,
} from "./client";
export interface QuoteLine {
  id: string;
  sku: string | null;
  description: string;
  qty: string;
  discount_paise: number;
  unit: string;
  options: Record<string, string>;
  needs_owner_pricing: boolean;
}
export interface Quote {
  id: string;
  quote_number: string;
  conversation_id: string;
  status: string;
  version: number;
  display_total: string;
  quote_discount_paise?: number;
  display_amounts: Record<string, string>;
  display_lines: {
    unit_price: string;
    addon: string;
    discount: string;
    taxable: string;
  }[];
  lines: QuoteLine[];
  customer_state: string | null;
  valid_until: string;
}
export interface QuoteSettings {
  auto_send_quotes: boolean;
  display_auto_send_limit: string;
  quote_validity_days: number;
  quote_terms: string;
}
export interface QuoteProfile {
  name: string;
  gstin: string | null;
  state_code: string | null;
  address: string | null;
  phone: string | null;
}
export interface LineEdit {
  sku: string;
  qty: string;
  discount_paise: number;
  options: Record<string, string>;
}
export const quotesApi = {
  list: () => request<Quote[]>("/quotes"),
  edit: (quote: Quote, lines: LineEdit[], customer_state: string | null) =>
    request<Quote>(`/quotes/${quote.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        expected_version: quote.version,
        lines,
        customer_state,
        discount_paise: quote.quote_discount_paise || 0,
      }),
    }),
  approve: (quote: Quote) =>
    request<Quote>(`/quotes/${quote.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ expected_version: quote.version }),
    }),
  mark: (quote: Quote, action: "accepted" | "rejected") =>
    request<Quote>(`/quotes/${quote.id}/mark-${action}`, {
      method: "POST",
      body: JSON.stringify({ expected_version: quote.version }),
    }),
  pdf: (id: string) => authenticatedDownload(`/quotes/${id}/pdf`),
  settings: () => request<QuoteSettings>("/tenant/settings"),
  saveSettings: (body: {
    auto_send_quotes: boolean;
    auto_send_limit_inr: string;
    quote_validity_days: number;
    quote_terms: string;
  }) =>
    request("/tenant/settings", { method: "PUT", body: JSON.stringify(body) }),
  profile: () => request<QuoteProfile>("/tenant/quote-profile"),
  saveProfile: (body: QuoteProfile) =>
    request("/tenant/quote-profile", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  logo: (file: File) => {
    const form = new FormData();
    form.set("file", file);
    return request("/tenant/logo", { method: "POST", body: form });
  },
};
export { saveChatFile as saveBlob } from "../../../widget/src/client";
