import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  saveChatFile,
  WidgetClient,
  type ChatMessage,
  type ChatSession,
} from "./client";
import { en } from "./i18n";
export interface WidgetProps {
  publicKey: string;
  apiBase: string;
  initiallyOpen?: boolean;
}
export function Widget({
  publicKey,
  apiBase,
  initiallyOpen = false,
}: WidgetProps) {
  const client = useMemo(() => new WidgetClient(apiBase), [apiBase]);
  const [open, setOpen] = useState(initiallyOpen);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [content, setContent] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const draft = useRef<{ content: string; id: string } | null>(null);
  useEffect(() => {
    if (!open || session) return;
    let active = true;
    setError("");
    client
      .start(publicKey)
      .then((value) => {
        if (active) setSession(value);
      })
      .catch(() => {
        if (active) setError(en.error);
      });
    return () => {
      active = false;
    };
  }, [open, session, publicKey, client, attempt]);
  useEffect(() => {
    if (!open || !session) return;
    const controller = new AbortController();
    void client.subscribe(session, setMessages, controller.signal).catch(() => {
      if (!controller.signal.aborted) setError(en.error);
    });
    return () => controller.abort();
  }, [client, open, session, attempt]);
  async function send(event: Event) {
    event.preventDefault();
    if (!session || !content.trim() || sending) return;
    if (draft.current?.content !== content)
      draft.current = { content, id: crypto.randomUUID() };
    setSending(true);
    setError("");
    try {
      const message = await client.send(session, content, draft.current.id);
      setMessages((previous) =>
        previous.some((existing) => existing.id === message.id)
          ? previous
          : [...previous, message],
      );
      setContent("");
      draft.current = null;
    } catch {
      setError(en.error);
    } finally {
      setSending(false);
    }
  }
  return (
    <div class="munim-widget">
      {open && (
        <section
          class="panel"
          role="dialog"
          aria-label={en.title(session?.business_name || "us")}
        >
          <header>
            <strong>{session?.business_name || en.launcher}</strong>
            <button
              type="button"
              class="close"
              aria-label={en.close}
              onClick={() => setOpen(false)}
            >
              ×
            </button>
          </header>
          <div class="messages" role="log" aria-live="polite">
            <p class="hint">{en.welcome}</p>
            {!session && !error && <p>{en.connecting}</p>}
            {messages.map((message) => (
              <div key={message.id} class={"bubble " + message.direction}>
                {message.content}
                {message.attachments
                  .filter((attachment) => attachment.quote_id)
                  .map((attachment) => (
                    <button
                      type="button"
                      key={attachment.quote_id}
                      onClick={() => {
                        if (session && attachment.quote_id)
                          void client
                            .quotePdf(session, attachment.quote_id)
                            .then((blob) => saveChatFile(blob, "quotation.pdf"))
                            .catch(() => setError(en.error));
                      }}
                    >
                      {en.downloadQuote}
                    </button>
                  ))}
              </div>
            ))}
          </div>
          {error && (
            <div class="error" role="alert">
              {error}
              <button
                type="button"
                onClick={() => {
                  setError("");
                  setAttempt((value) => value + 1);
                }}
              >
                {en.retry}
              </button>
            </div>
          )}
          <form onSubmit={send}>
            <label class="sr-only" for="munim-message">
              {en.message}
            </label>
            <input
              id="munim-message"
              value={content}
              onInput={(event) => setContent(event.currentTarget.value)}
              placeholder={en.message}
              maxLength={4000}
              disabled={!session}
              autoComplete="off"
            />
            <button disabled={!session || sending || !content.trim()}>
              {sending ? en.sending : en.send}
            </button>
          </form>
        </section>
      )}
      <button
        class="launcher"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {en.launcher}
      </button>
    </div>
  );
}
