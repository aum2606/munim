import { useState } from 'react'
import { Link, Route, Routes, useParams } from 'react-router-dom'

import { openPdf } from '../api/client'
import {
  useEditQuote,
  useQuote,
  useQuoteTransition,
  useQuotes,
  type LineEdit,
  type QuoteDetail,
  type QuoteStatus,
} from '../api/quotes'
import { t, type MessageKey } from '../i18n/en'
import { formatInr, paiseToRupees, rupeesToPaise } from '../lib/inr'

const STATUSES: QuoteStatus[] = ['pending_approval', 'sent', 'accepted', 'rejected', 'expired']
const statusLabel = (status: QuoteStatus) => t(`quotes.status.${status}` as MessageKey)
const button = 'rounded-md px-4 py-2 disabled:opacity-60'

export function QuotesPage() {
  return (
    <Routes>
      <Route index element={<QuoteList />} />
      <Route path=":quoteId" element={<QuoteView />} />
    </Routes>
  )
}

function QuoteList() {
  const [status, setStatus] = useState<QuoteStatus | ''>('pending_approval')
  const quotes = useQuotes(status)
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{t('quotes.title')}</h1>
        <label className="text-sm text-slate-600">
          {t('quotes.filter')}{' '}
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as QuoteStatus | '')}
            className="rounded-md border border-slate-300 px-2 py-1"
          >
            <option value="">{t('quotes.all')}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {quotes.data?.length === 0 && <p className="text-slate-500">{t('quotes.empty')}</p>}
      <ul className="space-y-2">
        {quotes.data?.map((quote) => (
          <li key={quote.id}>
            <Link to={quote.id} className="block rounded-lg bg-white p-3 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium text-slate-900">{quote.quote_number}</p>
                  <p className="truncate text-sm text-slate-600">{quote.customer_name ?? '–'}</p>
                  <p className="text-xs text-slate-500">
                    {t('quotes.validUntil', { date: quote.valid_until })}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-semibold">{formatInr(quote.total_paise)}</p>
                  <p className="text-xs text-slate-500">{statusLabel(quote.status)}</p>
                </div>
              </div>
              {quote.unpriced_lines > 0 && (
                <p className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
                  {t('quotes.unpriced', { count: String(quote.unpriced_lines) })}
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

interface Draft {
  qty: string
  rate: string
  discount: string
}

function QuoteView() {
  const { quoteId } = useParams()
  const quote = useQuote(quoteId)
  if (!quote.data || !quoteId) return null
  // Remount when the server's numbers change, so the edit boxes show what was really saved.
  const q = quote.data
  const version = `${q.id}:${q.status}:${q.total_paise}:${q.items.map((i) => `${i.qty}/${i.unit_price_paise}/${i.discount_paise}`).join(',')}`
  return <QuoteEditor key={version} quote={q} />
}

function QuoteEditor({ quote }: { quote: QuoteDetail }) {
  const editable = quote.status === 'pending_approval'
  const initial = (): Record<string, Draft> =>
    Object.fromEntries(
      quote.items.map((i) => [
        i.id,
        {
          qty: i.qty,
          rate: paiseToRupees(i.unit_price_paise),
          discount: paiseToRupees(i.discount_paise),
        },
      ]),
    )
  const [drafts, setDrafts] = useState(initial)
  const [state, setState] = useState(quote.buyer_state_code ?? '')

  const edit = useEditQuote(quote.id)
  const approve = useQuoteTransition(quote.id, 'approve')
  const reject = useQuoteTransition(quote.id, 'reject')
  const accept = useQuoteTransition(quote.id, 'mark-accepted')
  const error = edit.error ?? approve.error ?? reject.error ?? accept.error
  const unpriced = quote.items.some((i) => i.needs_owner_pricing)

  const save = () => {
    const items: LineEdit[] = []
    for (const item of quote.items) {
      const draft = drafts[item.id]
      const rate = rupeesToPaise(draft?.rate ?? '')
      const discount = rupeesToPaise(draft?.discount ?? '')
      if (!draft || rate === null || discount === null) continue // the server would refuse it
      const changed =
        draft.qty !== item.qty || rate !== item.unit_price_paise || discount !== item.discount_paise
      if (changed) {
        items.push({
          id: item.id,
          qty: draft.qty,
          unit_price_paise: rate,
          discount_paise: discount,
        })
      }
    }
    edit.mutate({ items, buyer_state_code: state === '' ? null : state })
  }

  const field = (id: string, key: keyof Draft, label: string) => (
    <input
      aria-label={`${label}: ${quote.items.find((i) => i.id === id)?.description}`}
      inputMode="decimal"
      disabled={!editable}
      value={drafts[id]?.[key] ?? ''}
      onChange={(e) => setDrafts({ ...drafts, [id]: { ...drafts[id]!, [key]: e.target.value } })}
      className="w-full rounded border border-slate-300 px-2 py-1 text-right disabled:bg-slate-50"
    />
  )

  return (
    <div className="space-y-4">
      <Link to="/quotes" className="text-sm text-indigo-700 underline">
        {t('common.back')}
      </Link>
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{quote.quote_number}</h1>
        <p className="text-slate-600">
          {t('quote.customer', { name: quote.customer_name ?? '–' })}
        </p>
        <p className="text-sm text-slate-500">
          {statusLabel(quote.status)} · {t('quotes.validUntil', { date: quote.valid_until })}
        </p>
      </header>

      <section className="space-y-2">
        <h2 className="font-semibold">{t('quote.lines')}</h2>
        <ul className="space-y-2">
          {quote.items.map((item) => (
            <li
              key={item.id}
              className={`space-y-2 rounded-lg p-3 shadow-sm ${
                item.needs_owner_pricing ? 'bg-amber-50' : 'bg-white'
              }`}
            >
              <p className="font-medium">{item.description}</p>
              {item.needs_owner_pricing && (
                <p className="text-xs text-amber-800">{t('quote.needsPrice')}</p>
              )}
              <div className="grid grid-cols-3 gap-2 text-xs text-slate-600">
                <label>
                  {t('quote.qty')} ({item.unit}){field(item.id, 'qty', t('quote.qty'))}
                </label>
                <label>
                  {t('quote.rate')}
                  {field(item.id, 'rate', t('quote.rate'))}
                </label>
                <label>
                  {t('quote.discount')}
                  {field(item.id, 'discount', t('quote.discount'))}
                </label>
              </div>
              <p className="text-right text-sm">
                {t('quote.amount')}: <strong>{formatInr(item.line_total_paise)}</strong> · GST{' '}
                {item.gst_rate}%
              </p>
            </li>
          ))}
        </ul>
        {editable && (
          <div className="space-y-2">
            <label className="block text-sm text-slate-700">
              {t('quote.buyerState')}
              <input
                value={state}
                maxLength={2}
                onChange={(e) => setState(e.target.value)}
                className="mt-1 block w-24 rounded border border-slate-300 px-2 py-1"
              />
            </label>
            <button
              type="button"
              onClick={save}
              disabled={edit.isPending}
              className={`${button} border border-indigo-600 text-indigo-700`}
            >
              {t('quote.saveChanges')}
            </button>
          </div>
        )}
      </section>

      <section className="rounded-xl bg-white p-3 shadow-sm">
        <dl className="space-y-1 text-sm">
          {(
            [
              ['quote.subtotal', quote.subtotal_paise],
              ['quote.discountTotal', quote.discount_paise],
              ['quote.cgst', quote.cgst_paise],
              ['quote.sgst', quote.sgst_paise],
              ['quote.igst', quote.igst_paise],
              ['quote.roundOff', quote.round_off_paise],
            ] as [MessageKey, number][]
          ).map(([label, paise]) => (
            <div key={label} className="flex justify-between">
              <dt className="text-slate-600">{t(label)}</dt>
              <dd>{formatInr(paise)}</dd>
            </div>
          ))}
          <div className="flex justify-between border-t pt-1 text-base font-semibold">
            <dt>{t('quote.total')}</dt>
            <dd>{formatInr(quote.total_paise)}</dd>
          </div>
        </dl>
      </section>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error.message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void openPdf(`/quotes/${quote.id}/pdf`)}
          className={`${button} border border-slate-300`}
        >
          {t('quote.pdf')}
        </button>
        {editable && (
          <>
            <button
              type="button"
              disabled={unpriced || approve.isPending}
              onClick={() => approve.mutate(undefined)}
              className={`${button} bg-indigo-600 text-white`}
            >
              {t('quote.approve')}
            </button>
            <button
              type="button"
              disabled={reject.isPending}
              onClick={() => reject.mutate(undefined)}
              className={`${button} border border-red-300 text-red-700`}
            >
              {t('quote.reject')}
            </button>
          </>
        )}
        {quote.status === 'sent' && (
          <button
            type="button"
            disabled={accept.isPending}
            onClick={() => accept.mutate(undefined)}
            className={`${button} bg-green-600 text-white`}
          >
            {t('quote.accepted')}
          </button>
        )}
      </div>
      {editable && (
        <p className="text-xs text-slate-500">
          {unpriced ? t('quote.priceFirst') : t('quote.approveHelp')}
        </p>
      )}
    </div>
  )
}
