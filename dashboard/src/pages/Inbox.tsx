import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { knowledgeApi } from "../api/knowledge";
import { knowledge as t } from "../i18n/knowledge";
export function InboxPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: knowledgeApi.conversations,
    refetchInterval: 3000,
  });
  const current = selected || conversations.data?.[0]?.id;
  const messages = useQuery({
    queryKey: ["conversation-messages", current],
    queryFn: () => knowledgeApi.messages(current!),
    enabled: !!current,
    refetchInterval: 3000,
  });
  return (
    <div className="page-stack">
      <div>
        <h1>{t.inbox}</h1>
        <p>{t.readOnly}</p>
      </div>
      {(conversations.isError || messages.isError) && (
        <p role="alert">{t.error}</p>
      )}
      <div className="inbox-grid">
        <section className="panel conversation-list">
          {!conversations.data?.length && <p>{t.emptyInbox}</p>}
          {conversations.data?.map((conversation) => (
            <button
              className={current === conversation.id ? "selected" : ""}
              key={conversation.id}
              onClick={() => setSelected(conversation.id)}
            >
              <strong>{t.visitor}</strong>
              <span className="badge">{conversation.mode}</span>
              <small>
                {conversation.channel} · {conversation.status}
              </small>
            </button>
          ))}
        </section>
        <section className="panel">
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
        </section>
      </div>
    </div>
  );
}
