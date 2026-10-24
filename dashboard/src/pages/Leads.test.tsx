import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { leadsApi, type Lead } from "../api/leads";
import { api } from "../api/client";
import { LeadsPage } from "./Leads";
afterEach(() => vi.restoreAllMocks());
it("shows a kanban lead and saves a manual stage with an audited timeline", async () => {
  const lead: Lead = {
    id: "lead-one",
    conversation_id: "chat",
    stage: "engaged",
    stage_override: false,
    score: 40,
    summary: "Customer needs visiting cards",
    tags: [],
    category: "printing",
    display_estimated_value: "₹450.00",
    assigned_to: null,
    lost_reason: null,
    next_followup_at: null,
    requirements: { quantity: 500 },
  };
  vi.spyOn(leadsApi, "list").mockResolvedValue([lead]);
  vi.spyOn(leadsApi, "followups").mockResolvedValue([]);
  vi.spyOn(leadsApi, "events").mockResolvedValue([
    {
      id: "e",
      event_type: "stage",
      from_value: "new",
      to_value: "engaged",
      actor: "ai",
      note: "Workflow evidence",
      created_at: "2026-10-24T00:00:00Z",
    },
  ]);
  vi.spyOn(api, "me").mockResolvedValue({
    id: "u",
    name: "Owner",
    role: "staff",
    email: "demo@example.test",
    tenant_id: "t",
  });
  const patch = vi
    .spyOn(leadsApi, "patch")
    .mockResolvedValue({ ...lead, stage: "won", stage_override: true });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <LeadsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    await screen.findByRole("heading", { name: "Lead details" }),
  ).toBeTruthy();
  expect(
    screen.getByText("Estimated value: ₹450.00", { exact: false }),
  ).toBeTruthy();
  expect(await screen.findByText("Workflow evidence")).toBeTruthy();
  expect(screen.getByText("Stage changed")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Lead stage"), {
    target: { value: "won" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save lead" }));
  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith(
      "lead-one",
      expect.objectContaining({ stage: "won" }),
    ),
  );
});
