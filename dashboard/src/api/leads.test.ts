import { afterEach, expect, it, vi } from "vitest";
import { setTokens } from "./client";
import { watchInbox } from "./leads";
afterEach(() => {
  vi.unstubAllGlobals();
  setTokens(null);
});
it("refreshes bearer authentication and decodes a fragmented SSE frame", async () => {
  setTokens({
    access_token: "old",
    refresh_token: "refresh",
    token_type: "bearer",
  });
  const snapshot = {
    conversations: [],
    handoffs: [{ id: "h", summary: "Résumé" }],
    followups: [],
  };
  const bytes = new TextEncoder().encode(
    "event: inbox\ndata: " + JSON.stringify(snapshot) + "\n\n",
  );
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(bytes.slice(0, 65));
      controller.enqueue(bytes.slice(65));
      controller.close();
    },
  });
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(null, { status: 401 }))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: "new",
          refresh_token: "next",
          token_type: "bearer",
        }),
      ),
    )
    .mockResolvedValueOnce(new Response(stream));
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  const received = vi.fn(() => controller.abort());
  await watchInbox(received, controller.signal, () => {});
  expect(received).toHaveBeenCalledWith(snapshot);
  expect(fetcher.mock.calls[2][1].headers.Authorization).toBe("Bearer new");
  expect(fetcher.mock.calls[2][0]).toBe("/api/v1/conversations/stream");
});
