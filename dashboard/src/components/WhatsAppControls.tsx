import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { leadsApi } from "../api/leads";
import { whatsappApi, type WhatsAppConsent } from "../api/whatsapp";
import { wa as t } from "../i18n/whatsapp";
export function WhatsAppConsentForm({
  conversationId,
  consent,
}: {
  conversationId: string;
  consent: WhatsAppConsent;
}) {
  const cache = useQueryClient();
  const profile = useQuery({ queryKey: ["me"], queryFn: api.me });
  const save = useMutation({
    mutationFn: (form: FormData) =>
      whatsappApi.saveConsent(conversationId, {
        opted_in: form.get("opted_in") === "on",
        note: String(form.get("note")),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["wa-consent", conversationId],
      });
      void cache.invalidateQueries({ queryKey: ["wa-followup-options"] });
    },
  });
  return (
    <section className="channel-card">
      <h3>{t.consent}</h3>
      {consent.opted_out && <p>{t.withdrawn}</p>}
      {!consent.freeform_allowed && !consent.opted_out && <p>{t.closed}</p>}
      {profile.data?.role === "owner" && (
        <form
          key={conversationId + (consent.opted_in_at || "")}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(new FormData(e.currentTarget));
          }}
        >
          <label>
            <input
              type="checkbox"
              name="opted_in"
              defaultChecked={!!consent.opted_in_at}
            />
            {t.optedIn}
          </label>
          <label>
            {t.note}
            <input
              name="note"
              required
              minLength={3}
              maxLength={500}
              defaultValue={consent.consent_note}
            />
          </label>
          <button disabled={save.isPending}>{t.saveConsent}</button>
        </form>
      )}
      {save.isError && <p role="alert">{t.error}</p>}
    </section>
  );
}
export function WhatsAppFollowup({ id }: { id: string }) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState("");
  const options = useQuery({
    queryKey: ["wa-followup-options", id],
    queryFn: () => whatsappApi.followupOptions(id),
  });
  const template = options.data?.templates.find(
    (template) => template.id === selected,
  );
  const approve = useMutation({
    mutationFn: () => leadsApi.followup(id, "approve", selected),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["followups"] });
      void cache.invalidateQueries({ queryKey: ["wa-deliveries"] });
    },
  });
  return (
    <div>
      <label>
        {t.pickTemplate}
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">—</option>
          {options.data?.templates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name} ({template.language})
            </option>
          ))}
        </select>
      </label>
      {!options.data?.templates.length && <p>{t.noTemplates}</p>}
      {template && (
        <section>
          <strong>{t.preview}</strong>
          <p>{template.body_text}</p>
        </section>
      )}
      {options.data && !options.data.consent.opted_in_at && (
        <p>
          <Link to={"/inbox?conversation=" + options.data.conversation_id}>
            {t.needsConsent}
          </Link>
        </p>
      )}
      <button
        disabled={
          !template ||
          !options.data?.consent.opted_in_at ||
          options.data?.consent.opted_out ||
          approve.isPending
        }
        onClick={() => approve.mutate()}
      >
        {t.approve}
      </button>
      {(options.isError || approve.isError) && <p role="alert">{t.error}</p>}
    </div>
  );
}
