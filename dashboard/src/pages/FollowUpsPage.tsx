import { useState } from 'react'

import { useFollowUpActions, useFollowUps, type FollowUp } from '../api/followups'
import { t } from '../i18n/en'

export function FollowUpsPage() {
  const followUps = useFollowUps()
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">{t('followups.title')}</h1>
      <p className="text-sm text-slate-500">{t('followups.help')}</p>
      {followUps.data?.length === 0 && <p className="text-slate-500">{t('followups.empty')}</p>}
      <ul className="space-y-3">
        {followUps.data?.map((followUp) => (
          <Draft key={followUp.id} followUp={followUp} />
        ))}
      </ul>
    </div>
  )
}

function Draft({ followUp }: { followUp: FollowUp }) {
  const { send, dismiss } = useFollowUpActions(followUp.id)
  const [text, setText] = useState(followUp.draft)
  const error = send.error ?? dismiss.error
  return (
    <li className="space-y-2 rounded-lg bg-white p-3 shadow-sm">
      <p className="text-sm font-medium">
        {followUp.customer_name ?? ''} ·{' '}
        {t('followups.quote', { number: followUp.quote_number ?? '' })}
      </p>
      <textarea
        aria-label={followUp.quote_number ?? ''}
        rows={3}
        maxLength={2000}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="block w-full rounded-md border border-slate-300 px-3 py-2 text-base"
      />
      {!followUp.can_send && (
        <p role="note" className="text-sm text-amber-800">
          {t('followups.cannotSend')}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error.message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {followUp.can_send ? (
          <button
            type="button"
            disabled={send.isPending || !text.trim()}
            onClick={() => send.mutate(text.trim())}
            className="rounded-md bg-indigo-600 px-3 py-2 text-sm text-white disabled:opacity-60"
          >
            {t('followups.send')}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void navigator.clipboard.writeText(text)}
            className="rounded-md bg-indigo-600 px-3 py-2 text-sm text-white"
          >
            {t('followups.copy')}
          </button>
        )}
        <button
          type="button"
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate()}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          {t('followups.dismiss')}
        </button>
      </div>
    </li>
  )
}
