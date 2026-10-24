import { expect, it, vi, afterEach } from "vitest";
import { WidgetClient } from "./client";
afterEach(() => vi.unstubAllGlobals());
it("downloads quote PDFs using the session bearer only in the header", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response("%PDF-demo", {
        headers: { "Content-Type": "application/pdf" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const client = new WidgetClient("http://api");
  const blob = await client.quotePdf(
    {
      session_id: "s",
      conversation_id: "c",
      token: "synthetic-session-token",
      business_name: "Demo",
    },
    "q",
  );
  expect(blob.type).toBe("application/pdf");
  expect(fetcher).toHaveBeenCalledWith(
    "http://api/api/v1/widget/quotes/q/pdf",
    { headers: { Authorization: "Bearer synthetic-session-token" } },
  );
});
