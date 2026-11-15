import { useState, type FormEvent } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import {
  useCatalogItems,
  useDeleteDocument,
  useDeleteFaq,
  useDeleteItem,
  useDocuments,
  useFaqs,
  useGaps,
  useResolveGap,
  useSaveFaq,
  useUploadDocument,
  type Faq,
} from '../api/knowledge'
import { ImportWizard } from '../components/ImportWizard'
import { t, type MessageKey } from '../i18n/en'
import { formatInr } from '../lib/inr'

const TABS: { to: string; label: MessageKey }[] = [
  { to: 'catalogue', label: 'knowledge.catalogue' },
  { to: 'documents', label: 'knowledge.documents' },
  { to: 'faqs', label: 'knowledge.faqs' },
  { to: 'gaps', label: 'knowledge.gaps' },
]

export function KnowledgePage() {
  return (
    <div className="space-y-4">
      <nav className="flex gap-1 overflow-x-auto">
        {TABS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `whitespace-nowrap rounded-full px-4 py-1.5 text-sm ${
                isActive ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700 shadow-sm'
              }`
            }
          >
            {t(label)}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate to="catalogue" replace />} />
        <Route path="catalogue" element={<CatalogueTab />} />
        <Route path="documents" element={<DocumentsTab />} />
        <Route path="faqs" element={<FaqsTab />} />
        <Route path="gaps" element={<GapsTab />} />
      </Routes>
    </div>
  )
}

const inputClass = 'block w-full rounded-md border border-slate-300 px-3 py-2 text-base'
const primaryButton = 'rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60'

function CatalogueTab() {
  const [query, setQuery] = useState('')
  const [importing, setImporting] = useState(false)
  const items = useCatalogItems(query)
  const remove = useDeleteItem()

  if (importing) return <ImportWizard onClose={() => setImporting(false)} />

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label={t('catalogue.search')}
          placeholder={t('catalogue.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className={`${inputClass} min-w-0 basis-full sm:flex-1 sm:basis-0`}
        />
        <button type="button" onClick={() => setImporting(true)} className={primaryButton}>
          {t('catalogue.import')}
        </button>
        <a href="/api/v1/catalog/template.xlsx" className="text-sm text-indigo-700 underline">
          {t('catalogue.template')}
        </a>
      </div>
      <p className="text-xs text-slate-500">{t('catalogue.priceNote')}</p>
      {items.data?.length === 0 && <p className="text-slate-500">{t('catalogue.empty')}</p>}
      <ul className="space-y-2">
        {items.data?.map((item) => (
          <li
            key={item.id}
            className="flex items-start justify-between gap-3 rounded-lg bg-white p-3 shadow-sm"
          >
            <div className="min-w-0">
              <p className="font-medium text-slate-900">{item.name}</p>
              <p className="text-xs text-slate-500">
                {item.sku}
                {item.category ? ` · ${item.category}` : ''}
              </p>
            </div>
            <div className="text-right">
              <p className="font-semibold">{formatInr(item.base_price_paise)}</p>
              <p className="text-xs text-slate-500">
                {item.unit} · {item.gst_rate}% GST
              </p>
              <button
                type="button"
                onClick={() => {
                  if (window.confirm(`${t('catalogue.delete')}: ${item.name}?`))
                    remove.mutate(item.id)
                }}
                className="text-xs text-red-600 underline"
              >
                {t('catalogue.delete')}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function DocumentsTab() {
  const documents = useDocuments()
  const upload = useUploadDocument()
  const remove = useDeleteDocument()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (file) {
      upload.mutate(
        { file, title },
        {
          onSuccess: () => {
            setFile(null)
            setTitle('')
          },
        },
      )
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="space-y-2 rounded-xl bg-white p-4 shadow-sm">
        <h2 className="font-semibold">{t('documents.upload')}</h2>
        <p className="text-sm text-slate-500">{t('documents.help')}</p>
        <input
          type="file"
          accept=".pdf,.docx,.txt"
          aria-label={t('documents.upload')}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <input
          placeholder={t('documents.title')}
          maxLength={200}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className={inputClass}
        />
        {upload.error && (
          <p role="alert" className="text-sm text-red-600">
            {upload.error.message}
          </p>
        )}
        <button type="submit" disabled={!file || upload.isPending} className={primaryButton}>
          {t('documents.upload')}
        </button>
      </form>
      {documents.data?.length === 0 && <p className="text-slate-500">{t('documents.empty')}</p>}
      <ul className="space-y-2">
        {documents.data?.map((doc) => (
          <li
            key={doc.id}
            className="flex items-center justify-between gap-3 rounded-lg bg-white p-3 shadow-sm"
          >
            <div className="min-w-0">
              <p className="truncate font-medium">{doc.title}</p>
              <p
                className={`text-xs ${doc.status === 'failed' ? 'text-red-600' : 'text-slate-500'}`}
              >
                {doc.status}
                {doc.error ? `: ${doc.error}` : ''}
              </p>
            </div>
            <button
              type="button"
              onClick={() => remove.mutate(doc.id)}
              className="text-sm text-red-600 underline"
            >
              {t('documents.delete')}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function FaqsTab() {
  const faqs = useFaqs()
  const save = useSaveFaq()
  const remove = useDeleteFaq()
  const [editing, setEditing] = useState<Faq | null>(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')

  const edit = (faq: Faq | null) => {
    setEditing(faq)
    setQuestion(faq?.question ?? '')
    setAnswer(faq?.answer ?? '')
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate({ id: editing?.id, question, answer }, { onSuccess: () => edit(null) })
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="space-y-2 rounded-xl bg-white p-4 shadow-sm">
        <label className="block text-sm font-medium">
          {t('faqs.question')}
          <input
            required
            maxLength={500}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm font-medium">
          {t('faqs.answer')}
          <textarea
            required
            maxLength={4000}
            rows={3}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            className={inputClass}
          />
        </label>
        {save.error && (
          <p role="alert" className="text-sm text-red-600">
            {save.error.message}
          </p>
        )}
        <button type="submit" disabled={save.isPending} className={primaryButton}>
          {t('faqs.save')}
        </button>
      </form>
      {faqs.data?.length === 0 && <p className="text-slate-500">{t('faqs.empty')}</p>}
      <ul className="space-y-2">
        {faqs.data?.map((faq) => (
          <li key={faq.id} className="rounded-lg bg-white p-3 shadow-sm">
            <p className="font-medium">{faq.question}</p>
            <p className="text-sm text-slate-600">{faq.answer}</p>
            <div className="mt-1 flex gap-3 text-sm">
              <button type="button" onClick={() => edit(faq)} className="text-indigo-700 underline">
                {t('faqs.edit')}
              </button>
              <button
                type="button"
                onClick={() => remove.mutate(faq.id)}
                className="text-red-600 underline"
              >
                {t('documents.delete')}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function GapCard({
  id,
  question,
  occurrences,
}: {
  id: string
  question: string
  occurrences: number
}) {
  const resolve = useResolveGap()
  const [answer, setAnswer] = useState('')
  return (
    <li className="space-y-2 rounded-lg bg-white p-3 shadow-sm">
      <p className="font-medium">{question}</p>
      <p className="text-xs text-slate-500">{t('gaps.asked', { count: String(occurrences) })}</p>
      <textarea
        aria-label={`${t('gaps.answer')}: ${question}`}
        placeholder={t('gaps.answer')}
        rows={2}
        maxLength={4000}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        className={inputClass}
      />
      <div className="flex gap-3">
        <button
          type="button"
          disabled={!answer.trim() || resolve.isPending}
          onClick={() => resolve.mutate({ id, answer })}
          className={primaryButton}
        >
          {t('gaps.save')}
        </button>
        <button
          type="button"
          onClick={() => resolve.mutate({ id, answer: null })}
          className="text-sm text-slate-600 underline"
        >
          {t('gaps.ignore')}
        </button>
      </div>
    </li>
  )
}

function GapsTab() {
  const gaps = useGaps()
  return (
    <div className="space-y-3">
      {gaps.data?.length === 0 && <p className="text-slate-500">{t('gaps.empty')}</p>}
      <ul className="space-y-2">
        {gaps.data?.map((gap) => (
          <GapCard key={gap.id} id={gap.id} question={gap.question} occurrences={gap.occurrences} />
        ))}
      </ul>
    </div>
  )
}
