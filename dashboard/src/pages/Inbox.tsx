import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { knowledgeApi } from "../api/knowledge";
import { leadsApi } from "../api/leads";
import { lt as t } from "../i18n/leads";
export function InboxPage() {
  const cache = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [reply, setReply] = useState("");
  const [externalId, setExternalId] = useState(() => crypto.randomUUID());
  const [search, setSearch] = useState("");
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: knowledgeApi.conversations,
    refetchInterval: 10000,
  });
  const visible = conversations.data?.filter(
    (c) => !search || c.id.includes(search) || c.mode.includes(search),
  );
  const current = params.get("conversation") || visible?.[0]?.id;
  const conversation = conversations.data?.find((c) => c.id === current);
  const messages = useQuery({
    queryKey: ["conversation-messages", current],
    queryFn: () => knowledgeApi.messages(current!),
    enabled: !!current,
    refetchInterval: 5000,
  });
  const drafts = useQuery({
    queryKey: ["drafts", current],
    queryFn: () => leadsApi.drafts(current!),
    enabled: !!current,
    refetchInterval: 5000,
  });
  const refresh = () => {
    for (const key of [
      "conversations",
      "conversation-messages",
      "drafts",
      "handoffs",
    ])
      void cache.invalidateQueries({ queryKey: [key] });
  };
  const mode = useMutation({
    mutationFn: (value: string) => leadsApi.mode(current!, value),
    onSuccess: refresh,
  });
  const send = useMutation({
    mutationFn: () => leadsApi.reply(current!, reply, externalId),
    onSuccess: () => {
      setReply("");
      setExternalId(crypto.randomUUID());
      refresh();
    },
  });
  const approve = useMutation({
    mutationFn: leadsApi.approveDraft,
    onSuccess: refresh,
  });
  const canReply =
    !!conversation &&
    conversation.mode !== "ai" &&
    conversation.status === "open";
  return (
    <div className="page-stack">
      <h1>{t.inbox}</h1>
      {(mode.isError ||
        send.isError ||
        approve.isError ||
        conversations.isError ||
        messages.isError ||
        drafts.isError) && <p role="alert">{t.error}</p>}
      <div className="inbox-grid">
        <section className="panel conversation-list">
          <label>
            {t.search}
            <input value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          {!visible?.length && <p>{t.emptyInbox}</p>}
          {visible?.map((c) => (
            <button
              className={c.id === current ? "selected" : ""}
              key={c.id}
              onClick={() => {
                setParams({ conversation: c.id });
                setReply("");
                setExternalId(crypto.randomUUID());
              }}
            >
              <strong>{t.visitor}</strong>
              <span className="badge">{c.mode}</span>
              <small>
                {c.channel} · {c.id.slice(0, 8)}
              </small>
            </button>
          ))}
        </section>
        <section className="panel">
          {conversation && (
            <div className="inbox-actions">
              <span className="badge">{conversation.mode}</span>
              <button
                disabled={mode.isPending || conversation.mode === "human"}
                onClick={() => mode.mutate("human")}
              >
                {t.takeover}
              </button>
              <button
                disabled={mode.isPending || conversation.mode === "assist"}
                onClick={() => mode.mutate("assist")}
              >
                {t.assist}
              </button>
              <button
                disabled={mode.isPending || conversation.mode === "ai"}
                onClick={() => mode.mutate("ai")}
              >
                {t.returnAI}
              </button>
            </div>
          )}
          <div role="log" className="chat-log">
            {messages.data?.map((message) => (
              <div
                className={"chat-message " + message.direction}
                key={message.id}
              >
                <p>{message.content}</p>
              </div>
            ))}
            {!messages.data?.length && <p className="muted">{t.noMessages}</p>}
          </div>
          {!!drafts.data?.length && (
            <section className="assist-drafts">
              <h2>{t.private}</h2>
              <p>{t.privateHint}</p>
              {drafts.data.map((draft) => (
                <article key={draft.id}>
                  <p>{draft.content}</p>
                  <button
                    disabled={
                      approve.isPending || conversation?.mode !== "assist"
                    }
                    onClick={() => approve.mutate(draft.id)}
                  >
                    {t.approve}
                  </button>
                </article>
              ))}
            </section>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send.mutate();
            }}
          >
            <label>
              {t.reply}
              <textarea
                value={reply}
                maxLength={4000}
                disabled={!canReply}
                onChange={(e) => {
                  setReply(e.target.value);
                  setExternalId(crypto.randomUUID());
                }}
              />
            </label>
            {!canReply && <p>{t.modeHint}</p>}
            <button disabled={!canReply || !reply.trim() || send.isPending}>
              {t.send}
            </button>
            {send.isSuccess && <p role="status">{t.sent}</p>}
          </form>
        </section>
      </div>
    </div>
  );
}
