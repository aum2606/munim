import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import { mockApi, renderAt } from '../test/helpers'
import { ForgotPasswordPage, ResetPasswordPage } from './PasswordResetPages'

it('asks for a link and says the same thing whatever the address', async () => {
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/auth/refresh') return { status: 401 }
    if (url === '/api/v1/auth/forgot-password' && init?.method === 'POST') {
      return { status: 202, body: { detail: 'sent' } }
    }
  })
  renderAt(<ForgotPasswordPage />, '/forgot-password')
  await userEvent.type(await screen.findByLabelText('Email'), 'owner@example.com')
  await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }))

  expect(await screen.findByRole('status')).toHaveTextContent('If that address has an account')
  const call = fetchMock.mock.calls.find(([url]) => url === '/api/v1/auth/forgot-password')
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ email: 'owner@example.com' })
})

it('sets a new password with the token from the link', async () => {
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/auth/reset-password' && init?.method === 'POST') return { status: 204 }
  })
  renderAt(<ResetPasswordPage />, '/reset-password?token=abc123')
  await userEvent.type(await screen.findByLabelText('New password'), 'a good new password')
  await userEvent.click(screen.getByRole('button', { name: 'Set password' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Your password is changed')
  const call = fetchMock.mock.calls.find(([url]) => url === '/api/v1/auth/reset-password')
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    token: 'abc123',
    password: 'a good new password',
  })
})

it('explains an expired or used link', async () => {
  mockApi((url) => {
    if (url === '/api/v1/auth/reset-password') {
      return { status: 409, body: { error: { code: 'conflict', message: 'expired' } } }
    }
  })
  renderAt(<ResetPasswordPage />, '/reset-password?token=old')
  await userEvent.type(await screen.findByLabelText('New password'), 'a good new password')
  await userEvent.click(screen.getByRole('button', { name: 'Set password' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid or has expired')
})
