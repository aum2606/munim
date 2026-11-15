import { useSession } from '../api/auth'
import { t } from '../i18n/en'

export function HomePage() {
  const me = useSession().data
  if (!me) return null

  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold text-slate-900">
        {t('home.welcome', { name: me.user.name })}
      </h1>
      <p className="text-slate-600">
        {t('home.workspace', { business: me.tenant.name, role: me.user.role })}
      </p>
      <p className="text-slate-500">{t('home.next')}</p>
    </div>
  )
}
