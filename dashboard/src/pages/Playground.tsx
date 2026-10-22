import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { startPlayground, WidgetClient, type ChatMessage } from "../api/chat";
import { knowledgeApi } from "../api/knowledge";
import { Button } from "../components/ui/button";
import { knowledge as t } from "../i18n/knowledge";
export function PlaygroundPage() {
  const cache = useQueryClient();
  const [error, setError] = useState("");
  const [content, setContent] = useState("");
  const tenant = useQuery({
    queryKey: ["tenant"],
    queryFn: knowledgeApi.tenant,
  });
  const client = useMemo(
    () => new WidgetClient(tenant.data?.public_api_url || ""),
    [tenant.data?.public_api_url],
  );
  const session = useMutation({ mutationFn: startPlayground });
  const current = session.data;
  const messages = useQuery<ChatMessage[]>({
    queryKey: ["playground-messages", current?.session_id],
    queryFn: async () => [],
    enabled: false,
    initialData: [],
  });
  useEffect(() => {
    if (!current || !tenant.data) return;
    const controller = new AbortController();
    void client
      .subscribe(
        current,
        (values) =>
          cache.setQueryData(
            ["playground-messages", current.session_id],
            values,
          ),
        controller.signal,
      )
      .catch(() => {
        if (!controller.signal.aborted) setError(t.connectionError);
      });
    return () => controller.abort();
  }, [current, client, cache, tenant.data]);
  const send = useMutation({
    mutationFn: (value: string) =>
      client.send(current!, value, crypto.randomUUID()),
    onSuccess: () => {
      setContent("");
      void cache.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
  const lastMessage = messages.data
    .filter((message) => message.direction === "in")
    .at(-1)?.id;
  const traces = useQuery({
    queryKey: ["traces", lastMessage],
    queryFn: () => knowledgeApi.traces(lastMessage!),
    enabled: !!lastMessage,
    refetchInterval: lastMessage ? 2000 : false,
  });
  return (
    <div className="page-stack">
      <div>
        <h1>{t.playground}</h1>
        <p>{t.playgroundIntro}</p>
        <p className="badge">
          {tenant.data?.model_mode === "fake" ? t.offline : t.live}
        </p>
      </div>
      <div>
        <Button
          disabled={session.isPending}
          onClick={() => {
            setError("");
            session.mutate();
          }}
        >
          {current ? t.newConversation : t.start}
        </Button>
      </div>
      {(session.isError || send.isError || error) && (
        <p role="alert">{error || t.error}</p>
      )}
      <div className="playground-grid">
        <section className="panel chat-panel">
          <div className="chat-log" role="log" aria-live="polite">
            {messages.data.map((message) => (
              <div
                className={"chat-message " + message.direction}
                key={message.id}
              >
                <p>{message.content}</p>
                {message.attachments?.flatMap(
                  (attachment) => attachment.citations || [],
                ).length > 0 && (
                  <small>
                    {t.evidence}:{" "}
                    {message.attachments
                      .flatMap((attachment) => attachment.citations || [])
                      .join(", ")}
                  </small>
                )}
              </div>
            ))}
            {messages.data.length === 0 && (
              <p className="muted">{t.noMessages}</p>
            )}
          </div>
          <form
            className="chat-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (content.trim()) send.mutate(content);
            }}
          >
            <label>
              {t.message}
              <input
                value={content}
                onChange={(event) => setContent(event.target.value)}
                maxLength={4000}
                disabled={!current}
              />
            </label>
            <Button disabled={!current || send.isPending || !content.trim()}>
              {send.isPending ? t.sending : t.send}
            </Button>
          </form>
        </section>
        <aside className="panel trace-panel">
          <h2>{t.traces}</h2>
          {!traces.data?.length && (
            <p className="muted">
              {traces.isError ? t.roleTrace : t.emptyTraces}
            </p>
          )}
          {traces.data?.map((run) => (
            <details key={run.id}>
              <summary>
                <strong>{run.agent}</strong>{" "}
                <span className="badge">{run.status}</span>
                <small>
                  {run.model} · {run.latency_ms} ms
                </small>
              </summary>
              <p>
                {t.tokens}: {run.prompt_tokens} / {run.completion_tokens}
              </p>
              <pre>
                {JSON.stringify(
                  {
                    input: run.input,
                    output: run.output,
                    tools: run.tool_calls,
                    error: run.error,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          ))}
        </aside>
      </div>
    </div>
  );
}
