import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { whatsappApi } from "../api/whatsapp";
import { WhatsAppPage } from "./WhatsApp";
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>
        <WhatsAppPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.spyOn(api, "me").mockResolvedValue({
    id: "owner",
    tenant_id: "tenant",
    name: "Owner",
    role: "owner",
    email: "owner@example.test",
  });
  vi.spyOn(whatsappApi, "setup").mockResolvedValue({
    callback_url: "https://example.test/api/v1/webhooks/whatsapp",
    encryption_ready: true,
    webhook_ready: true,
    api_version_ready: true,
  });
  vi.spyOn(whatsappApi, "accounts").mockResolvedValue([]);
  vi.spyOn(whatsappApi, "deliveries").mockResolvedValue([]);
});
afterEach(() => vi.restoreAllMocks());
it("requires verified server setup and clears the token after connecting", async () => {
  const connect = vi.spyOn(whatsappApi, "connect").mockResolvedValue({
    id: "a",
    external_id: "123456789",
    business_account_id: "987654321",
    status: "active",
  });
  mount();
  const button = await screen.findByRole("button", {
    name: "Verify & connect",
  });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Phone number ID"), {
    target: { value: "123456789" },
  });
  fireEvent.change(screen.getByLabelText("WhatsApp business account ID"), {
    target: { value: "987654321" },
  });
  const token = screen.getByLabelText("Access token") as HTMLInputElement;
  expect(token.type).toBe("password");
  fireEvent.change(token, { target: { value: "synthetic-provider-token" } });
  fireEvent.click(button);
  await waitFor(() =>
    expect(connect).toHaveBeenCalledWith({
      phone_number_id: "123456789",
      business_account_id: "987654321",
      access_token: "synthetic-provider-token",
    }),
  );
  expect(await screen.findByText("Account connected")).toBeTruthy();
  await waitFor(() => expect(token.value).toBe(""));
});
it("requires explicit confirmation before retrying an uncertain delivery", async () => {
  const delivery = {
    id: "d",
    message_id: "m",
    conversation_id: "c",
    content_preview: "A reviewed reply",
    status: "uncertain" as const,
    attempts: 1,
    last_error: "acceptance_uncertain",
    provider_message_id: null,
    next_attempt_at: "2026-10-27",
  };
  vi.mocked(whatsappApi.deliveries).mockResolvedValue([delivery]);
  const resolve = vi
    .spyOn(whatsappApi, "resolve")
    .mockResolvedValue({ ...delivery, status: "queued" });
  mount();
  const retry = await screen.findByRole("button", {
    name: "Confirm & retry",
    hidden: true,
  });
  expect((retry as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(
    screen.getByLabelText(
      "I checked Meta and confirmed this message was not sent.",
    ),
  );
  fireEvent.click(retry);
  await waitFor(() =>
    expect(resolve).toHaveBeenCalledWith("d", { confirmed_not_sent: true }),
  );
});
it("keeps connection management unavailable to staff", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: "staff",
    tenant_id: "tenant",
    name: "Staff",
    role: "staff",
    email: "staff@example.test",
  });
  mount();
  expect(
    await screen.findByText("Only the owner can manage WhatsApp connections."),
  ).toBeTruthy();
  expect(whatsappApi.accounts).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Access token")).toBeNull();
});
