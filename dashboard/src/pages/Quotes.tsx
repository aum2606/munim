import { useSearchParams } from "react-router-dom";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  quotesApi,
  saveBlob,
  type Quote,
  type QuoteSettings,
  type QuoteProfile,
  type LineEdit,
} from "../api/quotes";
import { knowledgeApi } from "../api/knowledge";
import { Button } from "../components/ui/button";
import { qt as t } from "../i18n/quotes";

function OptionInput({
  onAdd,
}: {
  onAdd: (key: string, value: string) => void;
}) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  return (
    <div className="quote-option">
      <label>
        {t.option}
        <input
          value={name}
          maxLength={50}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        {t.value}
        <input
          value={value}
          maxLength={100}
          onChange={(event) => setValue(event.target.value)}
        />
      </label>
      <Button
        type="button"
        variant="outline"
        disabled={!name.trim() || !value.trim()}
        onClick={() => {
          onAdd(name.trim(), value.trim());
          setName("");
          setValue("");
        }}
      >
        {t.addOption}
      </Button>
    </div>
  );
}

function QuoteEditor({
  quote,
  onChange,
}: {
  quote: Quote;
  onChange: () => void;
}) {
  const [lines, setLines] = useState<LineEdit[]>(
    quote.lines.map((line) => ({
      sku: line.sku || "",
      qty: line.qty,
      discount_paise: line.discount_paise,
      options: line.options,
    })),
  );
  const [state, setState] = useState(quote.customer_state || "");
  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: knowledgeApi.catalog,
  });
  const save = useMutation({
    mutationFn: () => quotesApi.edit(quote, lines, state || null),
    onSuccess: onChange,
  });
  const approve = useMutation({
    mutationFn: () => quotesApi.approve(quote),
    onSuccess: onChange,
  });
  const mark = useMutation({
    mutationFn: (action: "accepted" | "rejected") =>
      quotesApi.mark(quote, action),
    onSuccess: onChange,
  });
  const download = useMutation({
    mutationFn: async () =>
      saveBlob(await quotesApi.pdf(quote.id), "quotation.pdf"),
  });
  const pending = quote.status === "pending_approval";
  const busy = save.isPending || approve.isPending || mark.isPending;
  function update(index: number, patch: Partial<LineEdit>) {
    setLines((previous) =>
      previous.map((line, i) => (i === index ? { ...line, ...patch } : line)),
    );
  }
  return (
    <section className="panel quote-detail">
      <h2>{quote.quote_number}</h2>
      <p className="badge">{quote.status.replaceAll("_", " ")}</p>
      <p>
        {t.total}: <strong>{quote.display_total}</strong>
      </p>
      <dl>
        {[
          [t.subtotal, "subtotal_paise"],
          [t.discount, "discount_paise"],
          [t.cgst, "cgst_paise"],
          [t.sgst, "sgst_paise"],
          [t.igst, "igst_paise"],
          [t.roundOff, "round_off_paise"],
        ].map(([label, key]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{quote.display_amounts[key]}</dd>
          </div>
        ))}
      </dl>
      <Button
        variant="outline"
        onClick={() => download.mutate()}
        disabled={download.isPending}
      >
        {t.pdf}
      </Button>
      {quote.lines.some((line) => line.needs_owner_pricing) && (
        <p role="alert">{t.unpriced}</p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        {lines.map((line, index) => (
          <fieldset key={index} disabled={!pending || busy}>
            <legend>{quote.lines[index]?.description || t.product}</legend>
            <label>
              {t.product} {index + 1}
              <select
                required
                value={line.sku}
                onChange={(event) => update(index, { sku: event.target.value })}
              >
                <option value="">{t.product}</option>
                {catalog.data
                  ?.filter((product) => product.is_active)
                  .map((product) => (
                    <option key={product.id} value={product.sku}>
                      {product.name} ({product.sku}) — {product.display_price}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              {t.quantity} {index + 1}
              <input
                required
                inputMode="decimal"
                pattern="[0-9]+(\.[0-9]{1,3})?"
                value={line.qty}
                onChange={(event) => update(index, { qty: event.target.value })}
              />
            </label>
            {Object.entries(line.options).map(([key, value]) => (
              <label key={key}>
                {key}
                <input
                  value={value}
                  onChange={(event) =>
                    update(index, {
                      options: { ...line.options, [key]: event.target.value },
                    })
                  }
                />
              </label>
            ))}
            <OptionInput
              onAdd={(key, value) =>
                update(index, { options: { ...line.options, [key]: value } })
              }
            />
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                setLines((previous) => previous.filter((_, i) => i !== index))
              }
            >
              {t.remove}
            </Button>
          </fieldset>
        ))}
        <label>
          {t.state}
          <input
            value={state}
            onChange={(event) => setState(event.target.value)}
            maxLength={2}
            disabled={!pending || busy}
          />
        </label>
        {pending && (
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                setLines((previous) => [
                  ...previous,
                  { sku: "", qty: "1", discount_paise: 0, options: {} },
                ])
              }
            >
              {t.addLine}
            </Button>
            <Button disabled={busy || !lines.length}>{t.save}</Button>
          </>
        )}
      </form>
      {pending && (
        <>
          <p className="muted">{t.pendingHint}</p>
          <Button
            onClick={() => approve.mutate()}
            disabled={
              busy ||
              quote.lines.some((line) => line.needs_owner_pricing) ||
              JSON.stringify(lines) !==
                JSON.stringify(
                  quote.lines.map((line) => ({
                    sku: line.sku || "",
                    qty: line.qty,
                    discount_paise: line.discount_paise,
                    options: line.options,
                  })),
                ) ||
              state !== (quote.customer_state || "")
            }
          >
            {t.approve}
          </Button>
        </>
      )}
      {["sent", "viewed"].includes(quote.status) && (
        <>
          <Button onClick={() => mark.mutate("accepted")} disabled={busy}>
            {t.accepted}
          </Button>
          <Button
            variant="outline"
            onClick={() => mark.mutate("rejected")}
            disabled={busy}
          >
            {t.rejected}
          </Button>
        </>
      )}
      {(save.isError ||
        approve.isError ||
        mark.isError ||
        download.isError) && <p role="alert">{t.error}</p>}
    </section>
  );
}

function SettingsForm({ settings }: { settings: QuoteSettings }) {
  const cache = useQueryClient();
  const save = useMutation({
    mutationFn: (form: FormData) =>
      quotesApi.saveSettings({
        auto_send_quotes: form.get("auto") === "on",
        auto_send_limit_inr: String(form.get("limit")),
        quote_validity_days: Number(form.get("validity")),
        quote_terms: String(form.get("terms")),
      }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["quote-settings"] }),
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate(new FormData(event.currentTarget));
  }
  return (
    <form onSubmit={submit} className="panel">
      <h2>{t.settings}</h2>
      <label>
        <input
          type="checkbox"
          name="auto"
          defaultChecked={settings.auto_send_quotes}
        />
        {t.auto}
      </label>
      <label>
        {t.limit}
        <input
          name="limit"
          defaultValue={settings.display_auto_send_limit}
          required
          maxLength={64}
        />
      </label>
      <label>
        {t.validity}
        <input
          name="validity"
          type="number"
          min={1}
          max={90}
          defaultValue={settings.quote_validity_days}
          required
        />
      </label>
      <label>
        {t.terms}
        <textarea
          name="terms"
          defaultValue={settings.quote_terms}
          maxLength={4000}
        />
      </label>
      <Button disabled={save.isPending}>{t.saveSettings}</Button>
      {save.isSuccess && <p role="status">{t.saved}</p>}
      {save.isError && <p role="alert">{t.error}</p>}
    </form>
  );
}
function ProfileForm({ profile }: { profile: QuoteProfile }) {
  const save = useMutation({
    mutationFn: (form: FormData) =>
      quotesApi.saveProfile({
        name: String(form.get("name")),
        gstin: String(form.get("gstin")) || null,
        state_code: String(form.get("state")) || null,
        address: String(form.get("address")) || null,
        phone: String(form.get("phone")) || null,
      }),
  });
  const logo = useMutation({ mutationFn: quotesApi.logo });
  return (
    <form
      className="panel"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(new FormData(event.currentTarget));
      }}
    >
      <h2>{t.profile}</h2>
      <label>
        {t.name}
        <input
          name="name"
          required
          maxLength={200}
          defaultValue={profile.name}
        />
      </label>
      <label>
        {t.gstin}
        <input name="gstin" maxLength={15} defaultValue={profile.gstin || ""} />
      </label>
      <label>
        {t.supplierState}
        <input
          name="state"
          maxLength={2}
          defaultValue={profile.state_code || ""}
        />
      </label>
      <label>
        {t.address}
        <textarea
          name="address"
          maxLength={1000}
          defaultValue={profile.address || ""}
        />
      </label>
      <label>
        {t.phone}
        <input name="phone" maxLength={20} defaultValue={profile.phone || ""} />
      </label>
      <Button disabled={save.isPending}>{t.saveProfile}</Button>
      <label>
        {t.logo}
        <input
          type="file"
          accept="image/png,image/jpeg"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) logo.mutate(file);
          }}
        />
      </label>
      {(save.isSuccess || logo.isSuccess) && <p role="status">{t.saved}</p>}
      {(save.isError || logo.isError) && <p role="alert">{t.error}</p>}
    </form>
  );
}
export function QuotesPage() {
  const [params] = useSearchParams();
  const [pendingOnly, setPendingOnly] = useState(!params.has("quote"));
  const [selected, setSelected] = useState<string | null>(params.get("quote"));
  const cache = useQueryClient();
  const quotes = useQuery({
    queryKey: ["quotes"],
    queryFn: quotesApi.list,
    refetchInterval: 5000,
  });
  const settings = useQuery({
    queryKey: ["quote-settings"],
    queryFn: quotesApi.settings,
  });
  const profile = useQuery({
    queryKey: ["quote-profile"],
    queryFn: quotesApi.profile,
  });
  const current = quotes.data?.find((quote) => quote.id === selected);
  return (
    <div className="page-stack">
      <h1>{t.title}</h1>
      {quotes.isError && <p role="alert">{t.error}</p>}
      {quotes.isPending && <p>{t.loading}</p>}
      {quotes.data?.length === 0 && <p>{t.empty}</p>}
      <div className="inbox-grid">
        <section className="conversation-list">
          <h2>{t.list}</h2>
          <label>
            <input
              type="checkbox"
              checked={pendingOnly}
              onChange={(event) => setPendingOnly(event.target.checked)}
            />
            {t.pendingOnly}
          </label>
          {quotes.data
            ?.filter(
              (quote) => !pendingOnly || quote.status === "pending_approval",
            )
            .map((quote) => (
              <button
                type="button"
                key={quote.id}
                onClick={() => setSelected(quote.id)}
                className={selected === quote.id ? "selected" : ""}
              >
                <strong>{quote.quote_number}</strong>
                <small>
                  {quote.status.replaceAll("_", " ")} · {quote.display_total}
                </small>
              </button>
            ))}
        </section>
        {current && (
          <QuoteEditor
            key={current.id + current.version + current.status}
            quote={current}
            onChange={() => {
              void cache.invalidateQueries({ queryKey: ["quotes"] });
            }}
          />
        )}
      </div>
      {settings.data && <SettingsForm settings={settings.data} />}
      {profile.data && <ProfileForm profile={profile.data} />}
    </div>
  );
}
