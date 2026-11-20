import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useForgotPassword, useResetPassword } from '../api/auth'
import { ApiError } from '../api/client'
import { AuthCard, Field, SubmitButton } from '../components/Form'
import { t } from '../i18n/en'

export function ForgotPasswordPage() {
  const forgot = useForgotPassword()
  const [email, setEmail] = useState('')

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    forgot.mutate(email)
  }

  return (
    <AuthCard title={t('forgot.title')}>
      {forgot.isSuccess ? (
        <p role="status" className="text-sm text-slate-700">
          {t('forgot.sent')}
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          <p className="text-sm text-slate-600">{t('forgot.help')}</p>
          <Field
            label={t('login.email')}
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {forgot.error && (
            <p role="alert" className="text-sm text-red-600">
              {t('error.generic')}
            </p>
          )}
          <SubmitButton busy={forgot.isPending}>{t('forgot.submit')}</SubmitButton>
        </form>
      )}
      <p className="text-sm">
        <Link to="/login" className="text-indigo-600 underline">
          {t('forgot.back')}
        </Link>
      </p>
    </AuthCard>
  )
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const reset = useResetPassword()
  const [password, setPassword] = useState('')

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    reset.mutate({ token, password })
  }

  const failed = reset.error
  const message =
    failed instanceof ApiError && failed.status === 409
      ? t('reset.badLink')
      : failed
        ? t('error.generic')
        : null

  return (
    <AuthCard title={t('reset.title')}>
      {reset.isSuccess ? (
        <p role="status" className="text-sm text-slate-700">
          {t('reset.done')}{' '}
          <Link to="/login" className="text-indigo-600 underline">
            {t('register.signIn')}
          </Link>
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          <Field
            label={t('reset.newPassword')}
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="text-xs text-slate-500">{t('register.passwordHint')}</p>
          {message && (
            <p role="alert" className="text-sm text-red-600">
              {message}
            </p>
          )}
          <SubmitButton busy={reset.isPending}>{t('reset.submit')}</SubmitButton>
        </form>
      )}
    </AuthCard>
  )
}
