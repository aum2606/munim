import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { knowledgeApi } from "../api/knowledge";
import { leadsApi } from "../api/leads";
import { InboxPage } from "./Inbox";
afterEach(() => vi.restoreAllMocks());
it("takes over before sending a staff reply and exposes private draft approval", async () => {
  let mode = "ai";
  vi.spyOn(knowledgeApi, "conversations").mockImplementation(async () => [
    {
      id: "c",
      channel: "web",
      mode,
      status: "open",
      last_customer_msg_at: null,
      last_business_msg_at: null,
    },
  ]);
  vi.spyOn(knowledgeApi, "messages").mockResolvedValue([]);
  vi.spyOn(leadsApi, "drafts").mockResolvedValue([
    { id: "d", content: "Private suggestion", status: "pending" },
  ]);
  const change = vi
    .spyOn(leadsApi, "mode")
    .mockImplementation(async (_, value) => {
      mode = value;
    });
  const send = vi.spyOn(leadsApi, "reply").mockResolvedValue({
    id: "m",
    conversation_id: "c",
    direction: "out",
    content: "Staff response",
    created_at: "2026-10-24",
    attachments: [],
  });
  const approve = vi.spyOn(leadsApi, "approveDraft").mockResolvedValue({
    id: "m2",
    conversation_id: "c",
    direction: "out",
    content: "Private suggestion",
    created_at: "2026-10-24",
    attachments: [],
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <InboxPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const take = await screen.findByRole("button", { name: "Take over" });
  expect(
    (screen.getByLabelText("Staff reply") as HTMLTextAreaElement).disabled,
  ).toBe(true);
  fireEvent.click(take);
  await waitFor(() => expect(change).toHaveBeenCalledWith("c", "human"));
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Staff reply") as HTMLTextAreaElement).disabled,
    ).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Staff reply"), {
    target: { value: "Staff response" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      "c",
      "Staff response",
      expect.any(String),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Use assist mode" }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Approve & send",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Approve & send" }));
  await waitFor(() =>
    expect(approve).toHaveBeenCalledWith("d", expect.anything()),
  );
});
