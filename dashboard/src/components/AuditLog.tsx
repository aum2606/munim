import { useAuditLog } from '../api/audit'
import { t, type MessageKey } from '../i18n/en'

const LABELS: Record<string, MessageKey> = {
  whatsapp_connected: 'audit.whatsapp_connected',
  whatsapp_disconnected: 'audit.whatsapp_disconnected',
  customer_erased: 'audit.customer_erased',
  quote_edited: 'audit.quote_edited',
  quote_approved: 'audit.quote_approved',
  quote_rejected: 'audit.quote_rejected',
  user_created: 'audit.user_created',
  user_deactivated: 'audit.user_deactivated',
  user_reactivated: 'audit.user_reactivated',
}

const labelOf = (action: string) => (LABELS[action] ? t(LABELS[action]) : action)

/** Owner-only: who did the sensitive things, newest first. Holds no customer text. */
export function AuditLog() {
  const audit = useAuditLog()
  if (!audit.data) return null
  return (
    <section className="mt-8 space-y-3 border-t border-slate-200 pt-6">
      <h2 className="text-lg font-semibold">{t('audit.title')}</h2>
      <p className="text-sm text-slate-500">{t('audit.help')}</p>
      {audit.data.length === 0 ? (
        <p className="text-sm text-slate-500">{t('audit.none')}</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
          {audit.data.map((event) => (
            <li key={event.id} className="flex flex-wrap justify-between gap-x-4 py-2">
              <span>
                {labelOf(event.action)}
                {event.target && <span className="text-slate-500"> · {event.target}</span>}
              </span>
              <span className="text-slate-500">
                {event.actor ?? t('audit.system')} · {new Date(event.created_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
