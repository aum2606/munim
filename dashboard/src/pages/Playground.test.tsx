import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PlaygroundPage } from "./Playground";
import { knowledgeApi } from "../api/knowledge";
import * as chat from "../api/chat";
afterEach(() => vi.restoreAllMocks());
it("starts a test conversation, renders a streamed answer and sends through the typed client", async () => {
  const session = {
    session_id: "session",
    conversation_id: "conversation",
    token: "synthetic-token",
    business_name: "Demo",
  };
  vi.spyOn(knowledgeApi, "tenant").mockResolvedValue({
    id: "t",
    name: "Demo",
    business_type: "printing",
    widget_public_key: "public",
    widget_script_url: "https://api/widget.js",
    public_api_url: "https://api",
    model_mode: "fake",
  });
  vi.spyOn(chat, "startPlayground").mockResolvedValue(session);
  vi.spyOn(chat.WidgetClient.prototype, "subscribe").mockImplementation(
    async (_session, update, signal) => {
      update([
        {
          id: "reply",
          conversation_id: "conversation",
          direction: "out",
          content: "Cards: \u20b9450.00",
          created_at: "2026-10-22T00:00:00Z",
          attachments: [],
        },
      ]);
      await new Promise<void>((resolve) =>
        signal.addEventListener("abort", () => resolve(), { once: true }),
      );
    },
  );
  const send = vi.spyOn(chat.WidgetClient.prototype, "send").mockResolvedValue({
    id: "message",
    conversation_id: "conversation",
    direction: "in",
    content: "Hours?",
    created_at: "2026-10-22T00:00:00Z",
    attachments: [],
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <PlaygroundPage />
    </QueryClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Start test conversation" }),
  );
  expect(await screen.findByText("Cards: \u20b9450.00")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Hours?" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(session, "Hours?", expect.any(String)),
  );
});
