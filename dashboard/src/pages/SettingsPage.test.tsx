import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import { mockApi, renderAt } from '../test/helpers'
import { SettingsPage } from './SettingsPage'

const NOT_CONNECTED = {
  connected: false,
  phone_number_id: null,
  display_phone: null,
  webhook_ready: true,
}

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
    if (url === '/api/v1/channels/whatsapp') return { status: 200, body: NOT_CONNECTED }
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
    if (url === '/api/v1/channels/whatsapp') return { status: 200, body: NOT_CONNECTED }
  })
  renderAt(<SettingsPage />)
  await userEvent.type(await screen.findByLabelText('GSTIN'), 'BAD')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid request')
})

it('connects WhatsApp, sends the token once, and clears it from the page', async () => {
  let status: Record<string, unknown> = NOT_CONNECTED
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/tenant') return { status: 200, body: PROFILE }
    if (url === '/api/v1/channels/whatsapp' && init?.method === 'PUT') {
      status = {
        connected: true,
        phone_number_id: '110011',
        display_phone: '+91 98765',
        webhook_ready: true,
      }
      return { status: 200, body: status }
    }
    if (url === '/api/v1/channels/whatsapp') return { status: 200, body: status }
  })
  renderAt(<SettingsPage />)
  expect(await screen.findByText('Not connected.')).toBeInTheDocument()

  await userEvent.type(screen.getByLabelText('Phone number ID'), '110011')
  await userEvent.type(screen.getByLabelText('Access token'), 'EAAG-a-long-enough-token-123')
  await userEvent.click(screen.getByRole('button', { name: 'Connect' }))

  expect(await screen.findByText('Connected: +91 98765')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(
    ([, init]) => init?.method === 'PUT' && String(init?.body).includes('access_token'),
  )
  expect(JSON.parse(String(put?.[1]?.body))).toEqual({
    phone_number_id: '110011',
    display_phone: null,
    access_token: 'EAAG-a-long-enough-token-123',
  })
  expect(screen.getByLabelText('Access token')).toHaveValue('') // the secret does not stay on screen
  expect(screen.getByLabelText('Access token')).toHaveAttribute('type', 'password')
})

it('warns when the server cannot yet accept messages from Meta', async () => {
  mockApi((url) => {
    if (url === '/api/v1/tenant') return { status: 200, body: PROFILE }
    if (url === '/api/v1/channels/whatsapp') {
      return { status: 200, body: { ...NOT_CONNECTED, webhook_ready: false } }
    }
  })
  renderAt(<SettingsPage />)
  expect(await screen.findByText(/no WHATSAPP_VERIFY_TOKEN/)).toBeInTheDocument()
})
