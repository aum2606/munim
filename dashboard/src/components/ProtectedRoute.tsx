import { Navigate, Outlet } from 'react-router-dom'

import { useSession } from '../api/auth'
import { t } from '../i18n/en'

export function ProtectedRoute() {
  const session = useSession()
  if (session.isPending) {
    return <p className="p-6 text-slate-600">{t('common.loading')}</p>
  }
  if (!session.data) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}
