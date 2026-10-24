import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { KnowledgePage } from "./Knowledge";
import { MemoryRouter } from "react-router-dom";
import { leadsApi } from "../api/leads";
import { InboxPage } from "./Inbox";
import { knowledgeApi } from "../api/knowledge";
afterEach(() => vi.restoreAllMocks());
function mount(page: "knowledge" | "inbox" = "knowledge") {
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
        {page === "knowledge" ? <KnowledgePage /> : <InboxPage />}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("shows server formatted prices, document failures and installation snippet", async () => {
  vi.spyOn(knowledgeApi, "tenant").mockResolvedValue({
    id: "t",
    name: "Demo",
    business_type: "printing",
    widget_public_key: "public",
    widget_script_url: "https://api/widget.js",
    public_api_url: "https://api",
    model_mode: "fake",
  });
  vi.spyOn(knowledgeApi, "catalog").mockResolvedValue([
    {
      id: "c",
      sku: "CARD",
      name: "Visiting cards",
      display_price: "\u20b9450.00",
      gst_rate: 18,
      unit: "pack",
      is_active: true,
    },
  ]);
  vi.spyOn(knowledgeApi, "documents").mockResolvedValue([
    {
      id: "d",
      title: "Unreadable PDF",
      source_type: "pdf",
      status: "failed",
      error: "No readable text",
    },
  ]);
  vi.spyOn(knowledgeApi, "gaps").mockResolvedValue([]);
  const retry = vi.spyOn(knowledgeApi, "retry").mockResolvedValue({
    id: "d",
    title: "Unreadable PDF",
    source_type: "pdf",
    status: "pending",
    error: null,
  });
  mount();
  expect(await screen.findByText("\u20b9450.00")).toBeTruthy();
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "No readable text",
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(retry.mock.calls[0]?.[0]).toBe("d"));
  expect(screen.getByText(/data-key="public"/)).toBeTruthy();
});
it("shows import preview and commits only after explicit confirmation", async () => {
  vi.spyOn(knowledgeApi, "tenant").mockResolvedValue({
    id: "t",
    name: "Demo",
    business_type: "printing",
    widget_public_key: "public",
    widget_script_url: "https://api/widget.js",
    public_api_url: "https://api",
    model_mode: "fake",
  });
  vi.spyOn(knowledgeApi, "catalog").mockResolvedValue([]);
  vi.spyOn(knowledgeApi, "documents").mockResolvedValue([]);
  vi.spyOn(knowledgeApi, "gaps").mockResolvedValue([]);
  const preview = {
    id: "i",
    headers: ["sku", "name", "price"],
    mapping: { sku: "sku", name: "name", price: "price" },
    committed: false,
    rows: [
      {
        number: 2,
        catalog: { sku: "CARD", name: "Cards" },
        display_price: "\u20b9450.00",
        errors: [],
      },
    ],
  };
  vi.spyOn(knowledgeApi, "import").mockResolvedValue(preview);
  const commit = vi
    .spyOn(knowledgeApi, "commit")
    .mockResolvedValue({ ...preview, committed: true });
  mount();
  fireEvent.change(screen.getByLabelText("Upload catalogue"), {
    target: {
      files: [
        new File(["sku,name,price\nCARD,Cards,450"], "catalog.csv", {
          type: "text/csv",
        }),
      ],
    },
  });
  expect(await screen.findByText("Import preview")).toBeTruthy();
  expect(commit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm & import" }));
  expect(await screen.findByText("Catalogue imported")).toBeTruthy();
  expect(commit).toHaveBeenCalledWith("i", preview.mapping);
});
it("requires takeover before staff replies", async () => {
  vi.spyOn(leadsApi, "drafts").mockResolvedValue([]);
  vi.spyOn(knowledgeApi, "conversations").mockResolvedValue([
    {
      id: "conversation",
      channel: "web",
      mode: "ai",
      status: "open",
      last_customer_msg_at: null,
      last_business_msg_at: null,
    },
  ]);
  vi.spyOn(knowledgeApi, "messages").mockResolvedValue([
    {
      id: "m",
      conversation_id: "conversation",
      direction: "in",
      content: "Customer question",
      created_at: "2026-10-22T00:00:00Z",
      attachments: [],
    },
  ]);
  mount("inbox");
  expect(await screen.findByText("Customer question")).toBeTruthy();
  expect(
    (screen.getByLabelText("Staff reply") as HTMLTextAreaElement).disabled,
  ).toBe(true);
  expect(
    (screen.getByRole("button", { name: "Take over" }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
});
