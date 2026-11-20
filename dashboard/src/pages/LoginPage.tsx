import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { useLogin, useSession } from '../api/auth'
import { ApiError } from '../api/client'
import { AuthCard, Field, SubmitButton } from '../components/Form'
import { t } from '../i18n/en'

export function LoginPage() {
  const navigate = useNavigate()
  const session = useSession()
  const login = useLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (session.data) {
    return <Navigate to="/" replace />
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    login.mutate({ email, password }, { onSuccess: () => navigate('/', { replace: true }) })
  }

  const failed = login.error
  const message =
    failed instanceof ApiError && failed.status === 401
      ? t('error.invalidCredentials')
      : failed
        ? t('error.generic')
        : null

  return (
    <AuthCard title={t('login.title')}>
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          label={t('login.email')}
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label={t('login.password')}
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {message && (
          <p role="alert" className="text-sm text-red-600">
            {message}
          </p>
        )}
        <SubmitButton busy={login.isPending}>{t('login.submit')}</SubmitButton>
      </form>
      <p className="text-sm">
        <Link to="/forgot-password" className="text-indigo-600 underline">
          {t('login.forgot')}
        </Link>
      </p>
      <p className="text-sm text-slate-600">
        {t('login.noAccount')}{' '}
        <Link to="/register" className="text-indigo-600 underline">
          {t('login.createAccount')}
        </Link>
      </p>
    </AuthCard>
  )
}
