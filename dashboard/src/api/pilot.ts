import { authenticatedRequest as request } from "./client";
export interface Preferences {
  category: "printing" | "photography" | "interior" | "repair" | "electronics";
  tone: "friendly" | "formal";
  languages: string[];
  business_hours: Record<string, [string, string]>;
}
export interface OnboardingState {
  profile_ready: boolean;
  catalog_ready: boolean;
  knowledge_ready: boolean;
  tax_profile_ready: boolean;
  playground_tested: boolean;
  completed: boolean;
  preferences: Preferences;
}
export interface Customer {
  id: string;
  name: string | null;
  phone: string | null;
  email: string | null;
}
export interface Erasure {
  id: string;
  status: "pending_files" | "complete";
  files_remaining: number;
}
export const pilotApi = {
  state: () => request<OnboardingState>("/onboarding"),
  preferences: (body: Preferences) =>
    request<OnboardingState>("/onboarding/preferences", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  complete: () =>
    request<OnboardingState>("/onboarding/complete", { method: "POST" }),
  customers: (q: string) =>
    request<Customer[]>(`/customers?q=${encodeURIComponent(q)}`),
  erase: (customerId: string) =>
    request<Erasure>(`/customers/${customerId}`, {
      method: "DELETE",
      body: JSON.stringify({
        confirm_customer_id: customerId,
        retention_reviewed: true,
      }),
    }),
  retry: (id: string) =>
    request<Erasure>(`/privacy/erasures/${id}/retry`, { method: "POST" }),
};
