import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { useRegister, useSession } from '../api/auth'
import { ApiError } from '../api/client'
import { AuthCard, Field, SubmitButton } from '../components/Form'
import { t } from '../i18n/en'

export function RegisterPage() {
  const navigate = useNavigate()
  const session = useSession()
  const register = useRegister()
  const [form, setForm] = useState({
    business_name: '',
    business_type: '',
    name: '',
    email: '',
    password: '',
  })

  if (session.data) {
    return <Navigate to="/" replace />
  }

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    register.mutate(form, { onSuccess: () => navigate('/', { replace: true }) })
  }

  // The server's message is safe to show (it never echoes submitted values).
  const failed = register.error
  const message = failed instanceof ApiError ? failed.message : failed ? t('error.generic') : null

  return (
    <AuthCard title={t('register.title')}>
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          label={t('register.businessName')}
          required
          maxLength={120}
          value={form.business_name}
          onChange={set('business_name')}
        />
        <Field
          label={t('register.businessType')}
          required
          maxLength={60}
          value={form.business_type}
          onChange={set('business_type')}
        />
        <Field
          label={t('register.yourName')}
          autoComplete="name"
          required
          maxLength={120}
          value={form.name}
          onChange={set('name')}
        />
        <Field
          label={t('login.email')}
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={set('email')}
        />
        <Field
          label={`${t('login.password')} (${t('register.passwordHint')})`}
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          maxLength={128}
          value={form.password}
          onChange={set('password')}
        />
        {message && (
          <p role="alert" className="text-sm text-red-600">
            {message}
          </p>
        )}
        <SubmitButton busy={register.isPending}>{t('register.submit')}</SubmitButton>
      </form>
      <p className="text-sm text-slate-600">
        {t('register.haveAccount')}{' '}
        <Link to="/login" className="text-indigo-600 underline">
          {t('register.signIn')}
        </Link>
      </p>
    </AuthCard>
  )
}
