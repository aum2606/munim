export interface ChatSession {
  session_id: string;
  conversation_id: string;
  token: string;
  business_name: string;
}
export interface ChatMessage {
  id: string;
  conversation_id: string;
  direction: "in" | "out";
  content: string;
  created_at: string;
  attachments: { citations?: string[] }[];
}
export class WidgetClient {
  constructor(readonly base: string) {}
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(
      this.base.replace(/\/$/, "") + "/api/v1/widget" + path,
      init,
    );
    if (!response.ok)
      throw new Error(`Chat request failed: ${response.status}`);
    return response.json() as Promise<T>;
  }
  start(key: string) {
    return this.request<ChatSession>("/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });
  }
  send(session: ChatSession, content: string, externalId: string) {
    return this.request<ChatMessage>("/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify({
        session_id: session.session_id,
        external_id: externalId,
        content,
      }),
    });
  }
  async subscribe(
    session: ChatSession,
    update: (messages: ChatMessage[]) => void,
    signal: AbortSignal,
  ): Promise<void> {
    while (!signal.aborted) {
      const response = await fetch(
        this.base.replace(/\/$/, "") +
          `/api/v1/widget/stream/${session.session_id}`,
        { headers: { Authorization: `Bearer ${session.token}` }, signal },
      );
      if (!response.ok || !response.body)
        throw new Error("Chat stream unavailable");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      const cancel = () => {
        void reader.cancel();
      };
      signal.addEventListener("abort", cancel, { once: true });
      try {
        while (!signal.aborted) {
          const part = await reader.read();
          if (part.done) break;
          pending += decoder
            .decode(part.value, { stream: true })
            .replace(/\r\n/g, "\n");
          let boundary = pending.indexOf("\n\n");
          while (boundary >= 0) {
            const frame = pending.slice(0, boundary);
            pending = pending.slice(boundary + 2);
            const data = frame
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("\n");
            if (data) update(JSON.parse(data) as ChatMessage[]);
            boundary = pending.indexOf("\n\n");
          }
        }
      } finally {
        signal.removeEventListener("abort", cancel);
        reader.releaseLock();
      }
      if (!signal.aborted)
        await new Promise<void>((resolve) => {
          const timer = setTimeout(done, 1000);
          function done() {
            clearTimeout(timer);
            signal.removeEventListener("abort", done);
            resolve();
          }
          signal.addEventListener("abort", done, { once: true });
        });
    }
  }
}
