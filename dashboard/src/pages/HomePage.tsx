import { useNavigate } from 'react-router-dom'

import { useLogout, useSession } from '../api/auth'
import { t } from '../i18n/en'

// Layout shell for signed-in pages. Inbox, Quotes, Knowledge and Playground arrive with their phases.
export function HomePage() {
  const navigate = useNavigate()
  const me = useSession().data
  const logout = useLogout()
  if (!me) return null

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="flex items-center justify-between bg-white px-4 py-3 shadow-sm">
        <span className="text-lg font-semibold text-indigo-700">{t('app.name')}</span>
        <button
          type="button"
          onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login') })}
          className="text-sm text-slate-600 underline"
        >
          {t('common.signOut')}
        </button>
      </header>
      <main className="mx-auto max-w-3xl space-y-2 p-4">
        <h1 className="text-2xl font-semibold text-slate-900">
          {t('home.welcome', { name: me.user.name })}
        </h1>
        <p className="text-slate-600">
          {t('home.workspace', { business: me.tenant.name, role: me.user.role })}
        </p>
        <p className="text-slate-500">{t('home.next')}</p>
      </main>
    </div>
  )
}
