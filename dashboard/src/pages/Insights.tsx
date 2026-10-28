import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { insightsApi, type InsightAnswer, type Period } from "../api/insights";
import { AnalyticsTable, InsightChart } from "../components/InsightChart";
import { Button } from "../components/ui/button";
import { it } from "../i18n/insights";

function date(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
function Answer({ answer }: { answer: InsightAnswer }) {
  return (
    <div className="insight-answer">
      <p>{answer.text}</p>
      <small>
        {it.range}: {date(answer.period_start)} {it.from}{" "}
        {date(answer.period_end)}
      </small>
      {answer.chart_spec && <InsightChart spec={answer.chart_spec} />}
      {answer.table && !answer.chart_spec && (
        <AnalyticsTable
          result={{
            columns: answer.columns,
            rows: answer.table,
            total: answer.total,
            truncated: answer.truncated,
          }}
        />
      )}
      {answer.suggested_actions.length > 0 && (
        <>
          <h3>{it.actions}</h3>
          <ul>
            {answer.suggested_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
export function InsightsPage() {
  const [question, setQuestion] = useState("");
  const mutation = useMutation({ mutationFn: insightsApi.ask });
  const digest = useQuery({
    queryKey: ["weekly-digest"],
    queryFn: insightsApi.digest,
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (question.trim().length >= 3) mutation.mutate(question.trim());
  }
  return (
    <>
      <h1>{it.title}</h1>
      <section className="card">
        <h2>{it.ask}</h2>
        <form onSubmit={submit}>
          <label>
            {it.question}
            <textarea
              required
              minLength={3}
              maxLength={1000}
              placeholder={it.placeholder}
              value={question}
              onChange={(event) => {
                setQuestion(event.target.value);
                mutation.reset();
              }}
            />
          </label>
          <Button disabled={mutation.isPending || question.trim().length < 3}>
            {mutation.isPending ? it.pending : it.submit}
          </Button>
        </form>
        <div className="sample-questions">
          {it.sampleQuestions.map((sample) => (
            <Button
              variant="outline"
              key={sample}
              onClick={() => {
                setQuestion(sample);
                mutation.reset();
              }}
              disabled={mutation.isPending}
            >
              {sample}
            </Button>
          ))}
        </div>
        {mutation.isError && <p role="alert">{it.error}</p>}
        {mutation.data && (
          <section aria-label={it.answer} aria-live="polite">
            <Answer answer={mutation.data} />
          </section>
        )}
      </section>
      <section className="card">
        <h2>{it.digest}</h2>
        {digest.isPending ? (
          <p>{it.loading}</p>
        ) : digest.isError ? (
          <>
            <p role="alert">{it.error}</p>
            <Button onClick={() => void digest.refetch()}>{it.retry}</Button>
          </>
        ) : digest.data ? (
          <Answer answer={digest.data.answer} />
        ) : (
          <p>{it.digestEmpty}</p>
        )}
      </section>
    </>
  );
}
export function AnalyticsOverview() {
  const [period, setPeriod] = useState<Period>("30d");
  const query = useQuery({
    queryKey: ["analytics", period],
    queryFn: () => insightsApi.overview(period),
  });
  const overview = query.data;
  const response = overview?.first_response.rows[0]?.median_seconds;
  return (
    <section className="analytics-overview">
      <h2>{it.overview}</h2>
      <p>{it.subtitle}</p>
      <label>
        {it.period}
        <select
          value={period}
          onChange={(event) => setPeriod(event.target.value as Period)}
        >
          {Object.entries(it.periods).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {query.isPending && <p>{it.loading}</p>}
      {query.isError && (
        <>
          <p role="alert">{it.error}</p>
          <Button onClick={() => void query.refetch()}>{it.retry}</Button>
        </>
      )}
      {overview && (
        <>
          <small>
            {it.range}: {date(overview.period_start)} {it.from}{" "}
            {date(overview.period_end)}
          </small>
          <div className="insight-metrics">
            {[
              [it.enquiries, overview.enquiries],
              [it.messages, overview.inbound_messages],
              [
                it.response,
                response == null ? it.unavailable : `${response} ${it.seconds}`,
              ],
              [
                it.resolution,
                overview.ai_resolution_rate_pct == null
                  ? it.unavailable
                  : `${overview.ai_resolution_rate_pct}%`,
              ],
              [it.gaps, overview.open_gaps],
            ].map(([label, value]) => (
              <div className="card metric" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <p className="metric-definitions">{it.definitions}</p>
          <div className="insight-panels">
            {(
              [
                [it.trend, overview.trend, "date", "enquiries", "line"],
                [it.items, overview.top_items, "item", "enquiries", "bar"],
                [it.intents, overview.intent_mix, "intent", "messages", "bar"],
                [it.funnel, overview.funnel, "status", "quotes", "bar"],
                [it.channels, overview.channels, "channel", "enquiries", "bar"],
              ] as const
            ).map(([title, result, x_key, y_key, kind]) => (
              <section className="card" key={title}>
                <h3>{title}</h3>
                <InsightChart
                  spec={{ kind, title, x_key, y_key, rows: result.rows }}
                />
                {title === it.items && <small>{it.coverage}</small>}
              </section>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
