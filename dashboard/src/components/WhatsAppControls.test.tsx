import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { whatsappApi } from "../api/whatsapp";
import { WhatsAppFollowup } from "./WhatsAppControls";
afterEach(() => vi.restoreAllMocks());
it("previews the exact template and blocks approval without recorded opt-in", async () => {
  vi.spyOn(whatsappApi, "followupOptions").mockResolvedValue({
    conversation_id: "chat",
    consent: {
      opted_in_at: null,
      opted_out: false,
      consent_note: "",
      freeform_allowed: false,
    },
    templates: [
      {
        id: "t",
        account_id: "a",
        name: "followup",
        language: "en",
        status: "APPROVED",
        body_text: "Can we help with your enquiry?",
        usable: true,
      },
    ],
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <WhatsAppFollowup id="f" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: "followup (en)" });
  fireEvent.change(screen.getByLabelText("Approved WhatsApp template"), {
    target: { value: "t" },
  });
  expect(screen.getByText("Can we help with your enquiry?")).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Approve template & queue",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(screen.getByRole("link").getAttribute("href")).toBe(
    "/inbox?conversation=chat",
  );
});
