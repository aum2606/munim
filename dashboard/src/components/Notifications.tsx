import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { leadsApi, watchInbox } from "../api/leads";
import { lt as t } from "../i18n/leads";
export function Notifications() {
  const cache = useQueryClient();
  const [connected, setConnected] = useState(false);
  const handoffs = useQuery({
    queryKey: ["handoffs"],
    queryFn: leadsApi.handoffs,
  });
  const followups = useQuery({
    queryKey: ["followups"],
    queryFn: leadsApi.followups,
  });
  useEffect(() => {
    const controller = new AbortController();
    void watchInbox(
      (snapshot) => {
        cache.setQueryData(["conversations"], snapshot.conversations);
        cache.setQueryData(["handoffs"], snapshot.handoffs);
        cache.setQueryData(["followups"], snapshot.followups);
        for (const key of [
          "conversation-messages",
          "drafts",
          "leads",
          "lead-events",
        ])
          void cache.invalidateQueries({ queryKey: [key] });
      },
      controller.signal,
      setConnected,
    );
    return () => controller.abort();
  }, [cache]);
  const count = (handoffs.data?.length || 0) + (followups.data?.length || 0);
  return (
    <aside className="notifications" aria-label={t.notifications}>
      <small role="status">{connected ? t.live : t.reconnecting}</small>
      <details>
        <summary>
          {t.notifications} ({count})
        </summary>
        {!count && <p>{t.none}</p>}
        {handoffs.data?.map((handoff) => (
          <p key={handoff.id}>
            <Link to={"/inbox?conversation=" + handoff.conversation_id}>
              {handoff.reason}: {handoff.summary}
            </Link>
          </p>
        ))}
        {followups.data?.map((draft) => (
          <p key={draft.id}>
            <Link to={"/leads?lead=" + draft.lead_id}>
              {t.drafts}: {draft.kind}
            </Link>
          </p>
        ))}
      </details>
    </aside>
  );
}
