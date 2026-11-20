import { useState } from 'react'

import { useOverview } from '../api/metrics'
import { t } from '../i18n/en'
import { formatInr } from '../lib/inr'

const PERIODS = [7, 30, 90]

const usd = (micros: number) => `$${(micros / 1_000_000).toFixed(4)}`
const seconds = (ms: number | null) => (ms === null ? '–' : `${(ms / 1000).toFixed(1)} s`)

function Card({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg bg-white p-3 shadow-sm">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-semibold">{value}</p>
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

function Counts({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts)
  return (
    <div className="rounded-lg bg-white p-3 shadow-sm">
      <p className="mb-1 text-sm font-medium">{title}</p>
      {entries.length === 0 ? (
        <p className="text-sm text-slate-500">{t('metrics.none')}</p>
      ) : (
        <ul className="text-sm">
          {entries.map(([name, n]) => (
            <li key={name} className="flex justify-between">
              <span>{name.replace('_', ' ')}</span>
              <span className="font-medium">{n}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function MetricsPage() {
  const [days, setDays] = useState(7)
  const overview = useOverview(days)
  const data = overview.data
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{t('metrics.title')}</h1>
        <label className="text-sm text-slate-600">
          {t('metrics.period')}{' '}
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-slate-300 px-2 py-1"
          >
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                {t('metrics.lastDays', { days: String(p) })}
              </option>
            ))}
          </select>
        </label>
      </div>
      {overview.error && (
        <p role="alert" className="text-sm text-red-600">
          {overview.error.message}
        </p>
      )}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Card label={t('metrics.messages')} value={data.customer_messages} />
            <Card label={t('metrics.aiReplies')} value={data.ai_replies} />
            <Card label={t('metrics.staffReplies')} value={data.staff_replies} />
            <Card
              label={t('metrics.needPerson')}
              value={data.conversations_needing_a_person}
              hint={t('metrics.rightNow')}
            />
            <Card label={t('metrics.gaps')} value={data.open_knowledge_gaps} />
            <Card label={t('metrics.accepted')} value={formatInr(data.accepted_value_paise)} />
            <Card
              label={t('metrics.modelCalls')}
              value={data.model_calls_24h}
              hint={
                data.model_call_budget > 0
                  ? t('metrics.modelCallsOf', { limit: String(data.model_call_budget) })
                  : t('metrics.modelCallsNoLimit')
              }
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Counts title={t('metrics.leads')} counts={data.leads_by_stage} />
            <Counts title={t('metrics.quotes')} counts={data.quotes_by_status} />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Card
              label={t('metrics.costPerTurn')}
              value={usd(data.cost_per_turn_micros)}
              hint={t('metrics.costHint')}
            />
            <Card label={t('metrics.firstP50')} value={seconds(data.first_response_p50_ms)} />
            <Card label={t('metrics.firstP95')} value={seconds(data.first_response_p95_ms)} />
          </div>
          {data.unpriced_calls > 0 && (
            <p role="note" className="text-xs text-slate-500">
              {t('metrics.unpriced', { count: String(data.unpriced_calls) })}
            </p>
          )}
          {data.usage.length > 0 && (
            <div className="overflow-x-auto rounded-lg bg-white p-3 shadow-sm">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-slate-500">
                  <tr>
                    <th>{t('metrics.agent')}</th>
                    <th>{t('metrics.model')}</th>
                    <th>{t('metrics.calls')}</th>
                    <th>{t('metrics.errors')}</th>
                    <th>{t('metrics.cost')}</th>
                    <th>p95</th>
                  </tr>
                </thead>
                <tbody>
                  {data.usage.map((row) => (
                    <tr key={`${row.agent}-${row.model}`}>
                      <td>{row.agent}</td>
                      <td>{row.model ?? '–'}</td>
                      <td>{row.calls}</td>
                      <td>{row.errors}</td>
                      <td>{usd(row.cost_micros)}</td>
                      <td>{seconds(row.p95_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
