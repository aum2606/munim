import { useState, type FormEvent } from 'react'

import { useWhatsAppConnection, useWhatsAppStatus } from '../api/channels'
import { t } from '../i18n/en'
import { Field } from './Form'

/** Owner-only: connect the business's WhatsApp number. The token is write-only. */
export function WhatsAppSettings() {
  const status = useWhatsAppStatus()
  const { connect, disconnect } = useWhatsAppConnection()
  const [numberId, setNumberId] = useState('')
  const [displayPhone, setDisplayPhone] = useState('')
  const [token, setToken] = useState('')

  if (!status.data) return null

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    connect.mutate(
      {
        phone_number_id: numberId.trim(),
        display_phone: displayPhone.trim() || null,
        access_token: token.trim(),
      },
      { onSuccess: () => setToken('') }, // do not keep the secret in the page
    )
  }

  const error = connect.error ?? disconnect.error
  return (
    <section className="mt-8 space-y-3 border-t border-slate-200 pt-6">
      <h2 className="text-lg font-semibold">{t('whatsapp.title')}</h2>
      <p className="text-sm text-slate-500">{t('whatsapp.help')}</p>
      <p className="text-sm font-medium">
        {status.data.connected
          ? t('whatsapp.connected', {
              number: status.data.display_phone ?? status.data.phone_number_id ?? '',
            })
          : t('whatsapp.notConnected')}
      </p>
      {!status.data.webhook_ready && (
        <p role="note" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          {t('whatsapp.webhookNotReady')}
        </p>
      )}
      <p className="text-xs text-slate-500">{t('whatsapp.webhook')}</p>
      <form onSubmit={onSubmit} className="space-y-3">
        <Field
          label={t('whatsapp.numberId')}
          required
          inputMode="numeric"
          pattern="\d{5,32}"
          value={numberId}
          onChange={(e) => setNumberId(e.target.value)}
        />
        <Field
          label={t('whatsapp.displayPhone')}
          type="tel"
          maxLength={24}
          value={displayPhone}
          onChange={(e) => setDisplayPhone(e.target.value)}
        />
        <Field
          label={t('whatsapp.token')}
          required
          type="password"
          autoComplete="off"
          minLength={20}
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error.message}
          </p>
        )}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={connect.isPending}
            className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60"
          >
            {t('whatsapp.connect')}
          </button>
          {status.data.connected && (
            <button
              type="button"
              onClick={() => disconnect.mutate()}
              className="rounded-md border border-slate-300 px-4 py-2"
            >
              {t('whatsapp.disconnect')}
            </button>
          )}
        </div>
      </form>
    </section>
  )
}
