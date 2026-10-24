import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { leadsApi } from "../api/leads";
import { Notifications } from "./Notifications";
vi.mock("../api/leads", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/leads")>();
  return { ...original, watchInbox: vi.fn(async () => {}) };
});
afterEach(() => vi.restoreAllMocks());
it("links owner attention items to their conversation and lead", async () => {
  vi.spyOn(leadsApi, "handoffs").mockResolvedValue([
    {
      id: "h",
      conversation_id: "chat",
      reason: "complaint",
      summary: "Damaged order",
      status: "open",
    },
  ]);
  vi.spyOn(leadsApi, "followups").mockResolvedValue([
    {
      id: "f",
      lead_id: "lead",
      kind: "no_reply",
      draft_text: "Can we help?",
      status: "scheduled",
      scheduled_at: "2026-10-24",
      requires_template: false,
    },
  ]);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Notifications (2)")).toBeTruthy();
  const complaint = screen.getByText("complaint: Damaged order").closest("a");
  expect(complaint?.getAttribute("href")).toBe("/inbox?conversation=chat");
  expect(
    screen
      .getByText("Follow-up drafts: no_reply")
      .closest("a")
      ?.getAttribute("href"),
  ).toBe("/leads?lead=lead");
});
