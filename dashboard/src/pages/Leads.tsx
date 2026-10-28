import { WhatsAppFollowup } from "../components/WhatsAppControls";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  leadsApi,
  stages,
  type Lead,
  type Policy,
  type Stage,
} from "../api/leads";
import { lt as t } from "../i18n/leads";

function PolicyForm({ policy }: { policy: Policy }) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState(policy);
  const save = useMutation({
    mutationFn: () => leadsApi.savePolicy(draft),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["followup-policy"] });
    },
  });
  return (
    <form
      className="panel"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2>{t.policy}</h2>
      <p>{t.approvalHint}</p>
      <label>
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
        />
        {t.enabled}
      </label>
      {(["no_reply_days", "quote_reminder_days", "reengage_days"] as const).map(
        (key, index) => (
          <label key={key}>
            {[t.noReply, t.reminder, t.reengage][index]}
            <input
              type="number"
              min={key === "reengage_days" ? 2 : 1}
              max={
                key === "quote_reminder_days"
                  ? 30
                  : key === "no_reply_days"
                    ? 90
                    : 365
              }
              required
              value={draft[key]}
              onChange={(e) =>
                setDraft({ ...draft, [key]: Number(e.target.value) })
              }
            />
          </label>
        ),
      )}
      <button disabled={save.isPending}>{t.savePolicy}</button>
      {save.isError && <p role="alert">{t.error}</p>}
    </form>
  );
}
function LeadDetail({ lead, isOwner }: { lead: Lead; isOwner: boolean }) {
  const cache = useQueryClient();
  const events = useQuery({
    queryKey: ["lead-events", lead.id],
    queryFn: () => leadsApi.events(lead.id),
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: leadsApi.users,
    enabled: isOwner,
  });
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["leads"] });
    void cache.invalidateQueries({ queryKey: ["lead-events", lead.id] });
  };
  const save = useMutation({
    mutationFn: (form: FormData) =>
      leadsApi.patch(lead.id, {
        stage: String(form.get("stage")) as Stage,
        lost_reason: String(form.get("lost_reason") || "") || null,
        ...(isOwner && users.data
          ? { assigned_to: String(form.get("assigned_to") || "") || null }
          : {}),
        next_followup_at: form.get("next_followup_at")
          ? new Date(String(form.get("next_followup_at"))).toISOString()
          : null,
      }),
    onSuccess: refresh,
  });
  const resume = useMutation({
    mutationFn: () => leadsApi.patch(lead.id, { stage_override: false }),
    onSuccess: refresh,
  });
  return (
    <section id="lead-detail" className="panel">
      <h2>{t.detail}</h2>
      <p>{lead.summary}</p>
      <p>
        {t.score}: {lead.score} · {t.value}: {lead.display_estimated_value}
      </p>
      <Link to={"/inbox?conversation=" + lead.conversation_id}>
        {t.openChat}
      </Link>
      <p className="badge">{lead.stage_override ? t.override : t.automated}</p>
      <form
        key={lead.id + lead.stage}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(new FormData(e.currentTarget));
        }}
      >
        <label>
          {t.stageLabel}
          <select name="stage" defaultValue={lead.stage}>
            {stages.map((stage) => (
              <option key={stage} value={stage}>
                {t.stage[stage]}
              </option>
            ))}
          </select>
        </label>
        {isOwner && (
          <label>
            {t.assigned}
            <select name="assigned_to" defaultValue={lead.assigned_to || ""}>
              <option value="">{t.unassigned}</option>
              {users.data?.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          {t.lostReason}
          <input
            name="lost_reason"
            maxLength={500}
            defaultValue={lead.lost_reason || ""}
          />
        </label>
        <label>
          {t.next}
          <input
            type="datetime-local"
            name="next_followup_at"
            defaultValue={
              lead.next_followup_at
                ? new Date(
                    new Date(lead.next_followup_at).getTime() -
                      new Date().getTimezoneOffset() * 60000,
                  )
                    .toISOString()
                    .slice(0, 16)
                : ""
            }
          />
        </label>
        <button disabled={save.isPending}>{t.save}</button>
      </form>
      {lead.stage_override && (
        <button disabled={resume.isPending} onClick={() => resume.mutate()}>
          {t.resume}
        </button>
      )}
      {(save.isError || resume.isError || events.isError) && (
        <p role="alert">{t.error}</p>
      )}
      {save.isSuccess && <p role="status">{t.saved}</p>}
      <h3>{t.requirements}</h3>
      <dl>
        {Object.entries(lead.requirements).map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{String(value)}</dd>
          </div>
        ))}
      </dl>
      <h3>{t.timeline}</h3>
      <ol>
        {events.data?.map((event) => (
          <li key={event.id}>
            <strong>
              {t.events[event.event_type as keyof typeof t.events] ||
                t.events.update}
            </strong>
            {event.event_type === "stage" && (
              <span>
                : {t.stage[event.from_value as Stage] || event.from_value} →{" "}
                {t.stage[event.to_value as Stage] || event.to_value}
              </span>
            )}
            {event.event_type === "followup" && (
              <span>
                :{" "}
                {t.followupStatus[
                  event.to_value as keyof typeof t.followupStatus
                ] || event.to_value}
              </span>
            )}
            <p>
              {event.event_type === "manual_update" ? t.manualEdit : event.note}
            </p>
            <small>
              {new Date(event.created_at).toLocaleString()} ·{" "}
              {event.actor === "ai"
                ? t.actorAI
                : users.data?.find((user) => user.id === event.actor)?.name ||
                  t.actorStaff}
            </small>
          </li>
        ))}
      </ol>
    </section>
  );
}
export function LeadsPage() {
  const cache = useQueryClient();
  const [params, setParams] = useSearchParams();
  const leads = useQuery({
    queryKey: ["leads"],
    queryFn: leadsApi.list,
    refetchInterval: 10000,
  });
  const followups = useQuery({
    queryKey: ["followups"],
    queryFn: leadsApi.followups,
  });
  const profile = useQuery({ queryKey: ["me"], queryFn: api.me });
  const isOwner = profile.data?.role === "owner";
  const policy = useQuery({
    queryKey: ["followup-policy"],
    queryFn: leadsApi.policy,
    enabled: isOwner,
  });
  const action = useMutation({
    mutationFn: ({ id, value }: { id: string; value: "approve" | "cancel" }) =>
      leadsApi.followup(id, value),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["followups"] });
      void cache.invalidateQueries({ queryKey: ["lead-events"] });
    },
  });
  const current = params.get("lead") || leads.data?.[0]?.id;
  const lead = leads.data?.find((entry) => entry.id === current);
  return (
    <div className="page-stack">
      <h1>{t.title}</h1>
      {(leads.isError || followups.isError || action.isError) && (
        <p role="alert">{t.error}</p>
      )}
      {!leads.data?.length && <p>{t.empty}</p>}
      <div className="kanban">
        {stages.map((stage) => (
          <section key={stage} className="panel">
            <h2>
              {t.stage[stage]}{" "}
              <small>
                (
                {leads.data?.filter((lead) => lead.stage === stage).length || 0}
                )
              </small>
            </h2>
            {leads.data
              ?.filter((lead) => lead.stage === stage)
              .map((lead) => (
                <button
                  className={
                    "lead-card " + (current === lead.id ? "selected" : "")
                  }
                  key={lead.id}
                  onClick={() => setParams({ lead: lead.id })}
                >
                  <strong>
                    {lead.category} · {lead.id.slice(0, 8)}
                  </strong>
                  <p>{lead.summary}</p>
                  <small>
                    {t.score}: {lead.score} · {lead.display_estimated_value}
                  </small>
                  {lead.stage_override && (
                    <span className="badge">{t.override}</span>
                  )}
                </button>
              ))}
          </section>
        ))}
      </div>
      {lead ? (
        <LeadDetail key={lead.id} lead={lead} isOwner={isOwner} />
      ) : (
        <p>{t.select}</p>
      )}
      <section className="panel">
        <h2>{t.drafts}</h2>
        <p>{t.approvalHint}</p>
        {followups.data
          ?.filter((draft) => !lead || draft.lead_id === lead.id)
          .map((draft) => (
            <article className="followup-draft" key={draft.id}>
              <strong>{draft.kind}</strong>
              <p>{draft.draft_text}</p>
              {draft.requires_template && isOwner && (
                <WhatsAppFollowup id={draft.id} />
              )}
              {isOwner && (
                <>
                  <button
                    disabled={action.isPending || draft.requires_template}
                    onClick={() =>
                      action.mutate({ id: draft.id, value: "approve" })
                    }
                  >
                    {t.approve}
                  </button>
                  <button
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ id: draft.id, value: "cancel" })
                    }
                  >
                    {t.cancel}
                  </button>
                </>
              )}
            </article>
          ))}
      </section>
      {isOwner && policy.data && <PolicyForm policy={policy.data} />}
    </div>
  );
}
