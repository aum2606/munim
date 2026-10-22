import { cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, expect, it, vi } from "vitest";
import { Widget } from "./Widget";
const session = {
  session_id: "session",
  conversation_id: "conversation",
  token: "public-session-token",
  business_name: "Demo Printing",
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("opens, renders streamed answers, and submits a customer message", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "http://api/api/v1/widget/session")
      return new Response(JSON.stringify(session));
    if (url.includes("/stream/"))
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(
                "event: messages\ndata: " +
                  JSON.stringify([
                    {
                      id: "reply",
                      direction: "out",
                      content: "Visiting cards: \u20b9450.00",
                      attachments: [],
                    },
                  ]) +
                  "\n\n",
              ),
            );
          },
        }),
      );
    const body = JSON.parse(String(init?.body));
    expect(body.content).toBe("Are you open?");
    expect(init?.headers).toMatchObject({
      Authorization: "Bearer public-session-token",
    });
    return new Response(
      JSON.stringify({
        id: "customer",
        direction: "in",
        content: body.content,
        attachments: [],
      }),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  render(<Widget publicKey="synthetic-widget-key-123" apiBase="http://api" />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Chat with us" }));
  expect(await screen.findByText("Visiting cards: \u20b9450.00")).toBeTruthy();
  fireEvent.input(screen.getByLabelText("Message"), {
    target: { value: "Are you open?" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByText("Are you open?")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close chat" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("shows a connection error with an explicit retry", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
  render(
    <Widget
      publicKey="synthetic-widget-key-123"
      apiBase="http://api"
      initiallyOpen
    />,
  );
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Reconnect" })).toBeTruthy();
});
