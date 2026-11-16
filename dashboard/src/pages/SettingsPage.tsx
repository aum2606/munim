import { useState, type FormEvent } from 'react'

import { useProfile, useSaveProfile, type Profile } from '../api/profile'
import { Field } from '../components/Form'
import { WhatsAppSettings } from '../components/WhatsAppSettings'
import { t } from '../i18n/en'

interface Form {
  name: string
  business_type: string
  gstin: string
  address: string
  phone: string
  quote_terms: string
  quote_validity_days: string
}

const toForm = (p: Profile): Form => ({
  name: p.name,
  business_type: p.business_type,
  gstin: p.gstin ?? '',
  address: p.address ?? '',
  phone: p.phone ?? '',
  quote_terms: p.quote_terms ?? '',
  quote_validity_days: String(p.quote_validity_days),
})

export function SettingsPage() {
  const profile = useProfile()
  if (!profile.data) return null
  return (
    <>
      <ProfileForm profile={profile.data} />
      <WhatsAppSettings />
    </>
  )
}

function ProfileForm({ profile }: { profile: Profile }) {
  const save = useSaveProfile()
  const [form, setForm] = useState<Form>(() => toForm(profile))

  const set = (key: keyof Form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    const orNull = (text: string) => (text.trim() === '' ? null : text.trim())
    save.mutate({
      name: form.name,
      business_type: form.business_type,
      gstin: orNull(form.gstin),
      address: orNull(form.address),
      phone: orNull(form.phone),
      quote_terms: orNull(form.quote_terms),
      quote_validity_days: Number(form.quote_validity_days),
    })
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <h1 className="text-xl font-semibold">{t('settings.title')}</h1>
      <p className="text-sm text-slate-500">{t('settings.help')}</p>
      <Field
        label={t('settings.name')}
        required
        maxLength={120}
        value={form.name}
        onChange={set('name')}
      />
      <Field
        label={t('settings.type')}
        required
        maxLength={60}
        value={form.business_type}
        onChange={set('business_type')}
      />
      <Field
        label={t('settings.gstin')}
        maxLength={15}
        value={form.gstin}
        onChange={set('gstin')}
      />
      <p className="text-xs text-slate-500">
        {t('settings.state')}: {profile.state_code ?? '–'}
      </p>
      <Field
        label={t('settings.address')}
        maxLength={500}
        value={form.address}
        onChange={set('address')}
      />
      <Field label={t('settings.phone')} type="tel" value={form.phone} onChange={set('phone')} />
      <label className="block text-sm font-medium text-slate-700">
        {t('settings.terms')}
        <textarea
          rows={3}
          maxLength={2000}
          value={form.quote_terms}
          onChange={set('quote_terms')}
          className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-base"
        />
      </label>
      <Field
        label={t('settings.validity')}
        type="number"
        min={1}
        max={90}
        value={form.quote_validity_days}
        onChange={set('quote_validity_days')}
      />
      {save.error && (
        <p role="alert" className="text-sm text-red-600">
          {save.error.message}
        </p>
      )}
      {save.isSuccess && (
        <p role="status" className="text-sm text-green-700">
          {t('settings.saved')}
        </p>
      )}
      <button
        type="submit"
        disabled={save.isPending}
        className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60"
      >
        {t('common.save')}
      </button>
    </form>
  )
}
