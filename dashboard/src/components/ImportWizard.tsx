import { useState } from 'react'

import {
  CATALOG_FIELDS,
  useCommitImport,
  useSetMapping,
  useStartImport,
  type ImportPreview,
  type ImportResult,
} from '../api/knowledge'
import { t } from '../i18n/en'

/** Upload, check the column mapping and the problem rows, then save. Nothing is stored until the
 * owner presses save, and rows with problems are skipped, never guessed. */
export function ImportWizard({ onClose }: { onClose: () => void }) {
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const start = useStartImport()

  if (result) {
    return (
      <Panel onClose={onClose}>
        <p role="status">
          {t('import.done', {
            created: String(result.created),
            updated: String(result.updated),
            skipped: String(result.skipped),
          })}
        </p>
        <button type="button" onClick={onClose} className="mt-3 text-indigo-700 underline">
          {t('common.back')}
        </button>
      </Panel>
    )
  }

  if (!preview) {
    return (
      <Panel onClose={onClose}>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (file) start.mutate(file, { onSuccess: setPreview })
          }}
          className="space-y-3"
        >
          <label className="block text-sm font-medium text-slate-700">
            {t('import.choose')}
            <input
              type="file"
              accept=".xlsx,.csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
          {start.error && (
            <p role="alert" className="text-sm text-red-600">
              {start.error.message}
            </p>
          )}
          <button
            type="submit"
            disabled={!file || start.isPending}
            className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60"
          >
            {t('import.upload')}
          </button>
        </form>
      </Panel>
    )
  }

  return (
    <Panel onClose={onClose}>
      <Review preview={preview} onChange={setPreview} onDone={setResult} />
    </Panel>
  )
}

function Review({
  preview,
  onChange,
  onDone,
}: {
  preview: ImportPreview
  onChange: (p: ImportPreview) => void
  onDone: (r: ImportResult) => void
}) {
  const setMapping = useSetMapping(preview.job_id)
  const commit = useCommitImport(preview.job_id)
  const columns = preview.headers.filter(Boolean)

  const choose = (field: string, header: string) => {
    const mapping = { ...preview.mapping }
    delete mapping[field]
    if (header) mapping[field] = header
    setMapping.mutate(mapping, { onSuccess: onChange })
  }

  return (
    <div className="space-y-4">
      <section>
        <h3 className="font-medium text-slate-900">{t('import.mapping')}</h3>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {CATALOG_FIELDS.map((field) => (
            <label key={field} className="text-sm text-slate-700">
              {field}
              <select
                value={preview.mapping[field] ?? ''}
                onChange={(e) => choose(field, e.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1"
              >
                <option value="">{t('import.skip')}</option>
                {columns.map((header) => (
                  <option key={header} value={header}>
                    {header}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      </section>

      <p>
        {t('import.summary', {
          valid: String(preview.valid_count),
          total: String(preview.row_count),
          errors: String(preview.error_count),
        })}
      </p>
      {preview.missing_required.length > 0 && (
        <p role="alert" className="text-sm text-red-600">
          {t('import.missing', { fields: preview.missing_required.join(', ') })}
        </p>
      )}
      <ul className="space-y-1 text-sm">
        {preview.rows
          .filter((r) => r.errors.length > 0)
          .map((r) => (
            <li key={r.row} className="rounded bg-red-50 p-2 text-red-800">
              {t('import.row', { row: String(r.row) })}: {r.errors.join('; ')}
            </li>
          ))}
      </ul>
      {commit.error && (
        <p role="alert" className="text-sm text-red-600">
          {commit.error.message}
        </p>
      )}
      <button
        type="button"
        disabled={
          commit.isPending || preview.missing_required.length > 0 || preview.valid_count === 0
        }
        onClick={() => commit.mutate(undefined, { onSuccess: onDone })}
        className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60"
      >
        {t('import.commit', { valid: String(preview.valid_count) })}
      </button>
    </div>
  )
}

function Panel({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <section className="space-y-3 rounded-xl bg-white p-4 shadow">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('import.title')}</h2>
        <button type="button" onClick={onClose} className="text-sm text-slate-500 underline">
          {t('common.back')}
        </button>
      </div>
      {children}
    </section>
  )
}
