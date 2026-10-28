import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { pilotApi, type Preferences } from "../api/pilot";
import { quotesApi, type QuoteProfile } from "../api/quotes";
import { knowledgeApi } from "../api/knowledge";
import { KnowledgePage } from "./Knowledge";
import { PlaygroundPage } from "./Playground";
import { Button } from "../components/ui/button";
import { pt } from "../i18n/pilot";

function Profile({ profile }: { profile: QuoteProfile }) {
  const cache = useQueryClient();
  const save = useMutation({
    mutationFn: quotesApi.saveProfile,
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["onboarding"] });
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save.mutate({
      name: String(form.get("name")),
      address: String(form.get("address")),
      phone: String(form.get("phone")),
      state_code: String(form.get("state_code")),
      gstin: String(form.get("gstin")) || null,
    });
  }
  return (
    <form onSubmit={submit}>
      <p>{pt.profileHint}</p>
      {(
        [
          ["name", pt.name],
          ["address", pt.address],
          ["phone", pt.phone],
          ["state_code", pt.state],
          ["gstin", pt.gstin],
        ] as const
      ).map(([field, label]) => (
        <label key={field}>
          {label}
          <input
            name={field}
            defaultValue={profile[field] || ""}
            required={field !== "gstin"}
            maxLength={
              field === "gstin"
                ? 15
                : field === "state_code"
                  ? 2
                  : field === "phone"
                    ? 20
                    : 200
            }
          />
        </label>
      ))}
      <Button disabled={save.isPending}>{pt.save}</Button>
      {save.isSuccess && <p role="status">{pt.saved}</p>}
      {save.isError && <p role="alert">{pt.error}</p>}
    </form>
  );
}
function PreferencesForm({ preferences }: { preferences: Preferences }) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState(preferences);
  const [open, setOpen] = useState(
    preferences.business_hours.monday?.[0] || "10:00",
  );
  const [close, setClose] = useState(
    preferences.business_hours.monday?.[1] || "19:00",
  );
  const save = useMutation({
    mutationFn: () =>
      pilotApi.preferences({
        ...draft,
        business_hours: Object.fromEntries(
          [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
          ].map((day) => [day, [open, close]]),
        ),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["onboarding"] });
    },
  });
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label>
        {pt.category}
        <select
          value={draft.category}
          onChange={(event) =>
            setDraft({
              ...draft,
              category: event.target.value as Preferences["category"],
            })
          }
        >
          {Object.entries(pt.categories).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {pt.tone}
        <select
          value={draft.tone}
          onChange={(event) =>
            setDraft({
              ...draft,
              tone: event.target.value as Preferences["tone"],
            })
          }
        >
          <option value="friendly">{pt.friendly}</option>
          <option value="formal">{pt.formal}</option>
        </select>
      </label>
      <fieldset>
        <legend>{pt.languages}</legend>
        {Object.entries(pt.languageNames).map(([value, label]) => (
          <label className="consent-check" key={value}>
            <input
              type="checkbox"
              checked={draft.languages.includes(value)}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  languages: event.target.checked
                    ? [...draft.languages, value]
                    : draft.languages.filter((language) => language !== value),
                })
              }
            />
            {label}
          </label>
        ))}
      </fieldset>
      <p>{pt.hoursHint}</p>
      <label>
        {pt.open}
        <input
          type="time"
          required
          value={open}
          onChange={(event) => setOpen(event.target.value)}
        />
      </label>
      <label>
        {pt.close}
        <input
          type="time"
          required
          value={close}
          onChange={(event) => setClose(event.target.value)}
        />
      </label>
      <Button disabled={save.isPending || !draft.languages.length}>
        {pt.savePreferences}
      </Button>
      {save.isSuccess && <p role="status">{pt.saved}</p>}
      {save.isError && <p role="alert">{pt.error}</p>}
    </form>
  );
}
export function OnboardingPage() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const cache = useQueryClient();
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const state = useQuery({
    queryKey: ["onboarding"],
    queryFn: pilotApi.state,
    enabled: me.data?.role === "owner",
    refetchInterval: 5000,
  });
  const profile = useQuery({
    queryKey: ["quote-profile"],
    queryFn: quotesApi.profile,
    enabled: me.data?.role === "owner",
  });
  const tenant = useQuery({
    queryKey: ["tenant"],
    queryFn: knowledgeApi.tenant,
    enabled: me.data?.role === "owner",
  });
  const finish = useMutation({
    mutationFn: pilotApi.complete,
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["onboarding"] });
    },
  });
  if (me.isPending) return <p>{pt.loading}</p>;
  if (me.data?.role !== "owner") return <p>{pt.ownerOnly}</p>;
  async function next() {
    const fresh = await state.refetch();
    const value = fresh.data;
    if (
      !value ||
      (step === 0 && !value.profile_ready) ||
      (step === 1 && !(value.catalog_ready && value.knowledge_ready))
    ) {
      setError(pt.incomplete);
      return;
    }
    setError("");
    setStep(step + 1);
  }
  const snippet = tenant.data
    ? `<script src="${tenant.data.widget_script_url}" data-key="${tenant.data.widget_public_key}" data-api="${tenant.data.public_api_url}" defer></script>`
    : "";
  return (
    <div className="page-stack">
      <h1>{pt.title}</h1>
      <p>{pt.intro}</p>
      <ol className="setup-steps">
        {pt.steps.map((label, index) => (
          <li key={label} aria-current={step === index ? "step" : undefined}>
            {label}
          </li>
        ))}
      </ol>
      <section className="card">
        <h2>{pt.steps[step]}</h2>
        {state.isPending && <p>{pt.loading}</p>}
        {state.isError && <p role="alert">{pt.error}</p>}
        {step === 0 && profile.data && <Profile profile={profile.data} />}
        {step === 1 && (
          <>
            <p>{pt.knowledgeHint}</p>
            <KnowledgePage />
          </>
        )}
        {step === 2 && state.data && (
          <PreferencesForm preferences={state.data.preferences} />
        )}
        {step === 3 && (
          <>
            <p>{pt.testHint}</p>
            <PlaygroundPage />
          </>
        )}
        {step === 4 && (
          <>
            <p>{pt.publishHint}</p>
            <label>
              {pt.snippet}
              <textarea readOnly value={snippet} rows={5} />
            </label>
            <Link to="/whatsapp">{pt.whatsapp}</Link>
            {state.data && !state.data.tax_profile_ready && (
              <p role="alert">{pt.taxMissing}</p>
            )}
            <Button
              disabled={
                finish.isPending ||
                !state.data?.playground_tested ||
                !state.data.tax_profile_ready
              }
              onClick={() => finish.mutate()}
            >
              {pt.finish}
            </Button>
            {(state.data?.completed || finish.isSuccess) && (
              <p role="status">{pt.finished}</p>
            )}
            {finish.isError && <p role="alert">{pt.error}</p>}
          </>
        )}
        {error && <p role="alert">{error}</p>}
      </section>
      <div className="inbox-actions">
        {step > 0 && (
          <Button
            variant="outline"
            onClick={() => {
              setStep(step - 1);
              setError("");
            }}
          >
            {pt.back}
          </Button>
        )}
        {step < 4 && <Button onClick={() => void next()}>{pt.next}</Button>}
      </div>
    </div>
  );
}
