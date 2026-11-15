import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useLogout } from '../api/auth'
import { t, type MessageKey } from '../i18n/en'

const LINKS: { to: string; label: MessageKey }[] = [
  { to: '/', label: 'nav.home' },
  { to: '/knowledge', label: 'nav.knowledge' },
  { to: '/playground', label: 'nav.playground' },
  { to: '/inbox', label: 'nav.inbox' },
]

/** Header and navigation for every signed-in page. Scrolls sideways on a phone. */
export function AppShell() {
  const navigate = useNavigate()
  const logout = useLogout()
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white shadow-sm">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <span className="text-lg font-semibold text-indigo-700">{t('app.name')}</span>
          <button
            type="button"
            onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login') })}
            className="text-sm text-slate-600 underline"
          >
            {t('common.signOut')}
          </button>
        </div>
        <nav className="mx-auto flex max-w-4xl gap-1 overflow-x-auto px-2 pb-2">
          {LINKS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium ${
                  isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100'
                }`
              }
            >
              {t(label)}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-4xl p-4">
        <Outlet />
      </main>
    </div>
  )
}
