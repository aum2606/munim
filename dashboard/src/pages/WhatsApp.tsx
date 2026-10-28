import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import {
  whatsappApi,
  type WhatsAppAccount,
  type WhatsAppDelivery,
} from "../api/whatsapp";
import { wa as t } from "../i18n/whatsapp";
function Account({ account }: { account: WhatsAppAccount }) {
  const cache = useQueryClient();
  const templates = useQuery({
    queryKey: ["wa-templates", account.id],
    queryFn: () => whatsappApi.templates(account.id),
  });
  const sync = useMutation({
    mutationFn: () => whatsappApi.sync(account.id),
    onSuccess: (values) =>
      cache.setQueryData(["wa-templates", account.id], values),
  });
  const change = useMutation({
    mutationFn: () =>
      whatsappApi.change(
        account.id,
        account.status === "active" ? "disabled" : "active",
      ),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["wa-accounts"] });
    },
  });
  return (
    <article className="panel channel-card">
      <h3>
        {t.phone}: {account.external_id}
      </h3>
      <p>{account.status}</p>
      <button disabled={change.isPending} onClick={() => change.mutate()}>
        {account.status === "active" ? t.disable : t.enable}
      </button>
      <h3>{t.templates}</h3>
      <p>{t.templateHint}</p>
      <button disabled={sync.isPending} onClick={() => sync.mutate()}>
        {t.sync}
      </button>
      {(templates.isError || sync.isError || change.isError) && (
        <p role="alert">{t.error}</p>
      )}
      {templates.data?.map((template) => (
        <section className="followup-draft" key={template.id}>
          <strong>
            {template.name} ({template.language})
          </strong>
          <p>
            {template.status} · {template.usable ? t.usable : t.unsupported}
          </p>
          <p>{template.body_text}</p>
        </section>
      ))}
    </article>
  );
}
function Delivery({
  delivery,
  isOwner,
}: {
  delivery: WhatsAppDelivery;
  isOwner: boolean;
}) {
  const cache = useQueryClient();
  const [confirmed, setConfirmed] = useState(false);
  const [provider, setProvider] = useState("");
  const resolve = useMutation({
    mutationFn: (accepted: boolean) =>
      whatsappApi.resolve(
        delivery.id,
        accepted
          ? { provider_message_id: provider }
          : { confirmed_not_sent: confirmed },
      ),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["wa-deliveries"] });
    },
  });
  const attention = ["failed", "blocked", "uncertain"].includes(
    delivery.status,
  );
  return (
    <article className="channel-card">
      <p>
        <strong>{t.states[delivery.status]}</strong> · {t.attempts}:{" "}
        {delivery.attempts}
      </p>
      <p>{delivery.content_preview}</p>
      {delivery.conversation_id && (
        <Link to={"/inbox?conversation=" + delivery.conversation_id}>
          {t.open}
        </Link>
      )}
      {attention && isOwner && (
        <details>
          <summary>{t.reconcile}</summary>
          <p>{t.uncertain}</p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            {t.confirmed}
          </label>
          <button
            disabled={!confirmed || resolve.isPending}
            onClick={() => resolve.mutate(false)}
          >
            {t.retry}
          </button>
          <label>
            {t.providerId}
            <input
              value={provider}
              maxLength={512}
              onChange={(e) => setProvider(e.target.value)}
            />
          </label>
          <button
            disabled={!provider.startsWith("wamid.") || resolve.isPending}
            onClick={() => resolve.mutate(true)}
          >
            {t.markSent}
          </button>
        </details>
      )}
      {resolve.isError && <p role="alert">{t.error}</p>}
    </article>
  );
}
export function WhatsAppPage() {
  const cache = useQueryClient();
  const [connected, setConnected] = useState(false);
  const profile = useQuery({ queryKey: ["me"], queryFn: api.me });
  const isOwner = profile.data?.role === "owner";
  const setup = useQuery({
    queryKey: ["wa-setup"],
    queryFn: whatsappApi.setup,
    enabled: isOwner,
  });
  const accounts = useQuery({
    queryKey: ["wa-accounts"],
    queryFn: whatsappApi.accounts,
    enabled: isOwner,
  });
  const deliveries = useQuery({
    queryKey: ["wa-deliveries"],
    queryFn: whatsappApi.deliveries,
    refetchInterval: 5000,
  });
  const connect = useMutation({
    gcTime: 0,
    mutationFn: (form: FormData) =>
      whatsappApi.connect({
        phone_number_id: String(form.get("phone")),
        business_account_id: String(form.get("business")),
        access_token: String(form.get("token")),
      }),
    onSuccess: () => {
      setConnected(true);
      void cache.invalidateQueries({ queryKey: ["wa-accounts"] });
    },
  });
  const ready =
    setup.data?.encryption_ready &&
    setup.data.webhook_ready &&
    setup.data.api_version_ready;
  return (
    <div className="page-stack">
      <h1>{t.title}</h1>
      {!isOwner && profile.data && <p>{t.ownerOnly}</p>}
      {isOwner && (
        <>
          <section className="panel channel-card">
            <h2>{t.serverSetup}</h2>
            <p>{t.setupHint}</p>
            {setup.data && (
              <>
                <label>
                  {t.callback}
                  <input readOnly value={setup.data.callback_url} />
                </label>
                <ul>
                  <li>
                    {t.encryption}:{" "}
                    {setup.data.encryption_ready ? t.ready : t.missing}
                  </li>
                  <li>
                    {t.webhook}:{" "}
                    {setup.data.webhook_ready ? t.ready : t.missing}
                  </li>
                  <li>
                    {t.version}:{" "}
                    {setup.data.api_version_ready ? t.ready : t.missing}
                  </li>
                </ul>
              </>
            )}
            {!ready && <p>{t.notReady}</p>}
          </section>
          <form
            className="panel"
            onSubmit={(e) => {
              e.preventDefault();
              const element = e.currentTarget;
              connect.mutate(new FormData(element), {
                onSuccess: () => element.reset(),
              });
            }}
          >
            <h2>{t.setup}</h2>
            <p>{t.tokenHint}</p>
            <label>
              {t.phone}
              <input name="phone" pattern="[0-9]{5,30}" required />
            </label>
            <label>
              {t.business}
              <input name="business" pattern="[0-9]{5,30}" required />
            </label>
            <label>
              {t.token}
              <input
                name="token"
                type="password"
                autoComplete="off"
                minLength={10}
                maxLength={4096}
                required
              />
            </label>
            <button disabled={!ready || connect.isPending}>{t.connect}</button>
            {connected && <p role="status">{t.connected}</p>}
          </form>
          <h2>{t.accounts}</h2>
          {!accounts.data?.length && <p>{t.empty}</p>}
          {accounts.data?.map((account) => (
            <Account key={account.id} account={account} />
          ))}
        </>
      )}
      {(profile.isError ||
        setup.isError ||
        accounts.isError ||
        deliveries.isError ||
        connect.isError) && <p role="alert">{t.error}</p>}
      <section className="panel">
        <h2>{t.delivery}</h2>
        {!deliveries.data?.length && <p>{t.noDeliveries}</p>}
        {deliveries.data?.map((delivery) => (
          <Delivery
            key={delivery.id + delivery.status}
            delivery={delivery}
            isOwner={isOwner}
          />
        ))}
      </section>
    </div>
  );
}
