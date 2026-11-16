import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import { mockApi, renderAt } from '../test/helpers'
import { SettingsPage } from './SettingsPage'

const PROFILE = {
  id: 't1',
  name: 'Asha Press',
  business_type: 'printing',
  gstin: null,
  state_code: null,
  address: null,
  phone: null,
  quote_terms: null,
  quote_validity_days: 7,
}

it('saves the profile, turning blank boxes into null and showing the derived state', async () => {
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/tenant' && init?.method === 'PUT') {
      return { status: 200, body: { ...PROFILE, gstin: '24ABCDE1234F1Z5', state_code: '24' } }
    }
    if (url === '/api/v1/tenant') return { status: 200, body: PROFILE }
  })
  renderAt(<SettingsPage />)
  await userEvent.type(await screen.findByLabelText('GSTIN'), '24ABCDE1234F1Z5')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Saved.')
  expect(await screen.findByText('State code: 24')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(put?.[1]?.body))).toEqual({
    name: 'Asha Press',
    business_type: 'printing',
    gstin: '24ABCDE1234F1Z5',
    address: null,
    phone: null,
    quote_terms: null,
    quote_validity_days: 7,
  })
})

it('shows why the server refused a GSTIN', async () => {
  mockApi((url, init) => {
    if (init?.method === 'PUT') {
      return {
        status: 422,
        body: { error: { code: 'validation_error', message: 'Invalid request' } },
      }
    }
    if (url === '/api/v1/tenant') return { status: 200, body: PROFILE }
  })
  renderAt(<SettingsPage />)
  await userEvent.type(await screen.findByLabelText('GSTIN'), 'BAD')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid request')
})
