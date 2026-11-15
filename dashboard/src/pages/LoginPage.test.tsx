import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { expect, it } from 'vitest'

import { ME, mockApi, renderAt } from '../test/helpers'
import { HomePage } from './HomePage'
import { LoginPage } from './LoginPage'

function Routed() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<HomePage />} />
    </Routes>
  )
}

async function fillAndSubmit(password: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Email'), 'owner@example.com')
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

it('signs in and lands on the home page', async () => {
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/auth/refresh') return { status: 401 } // no session yet
    if (url === '/api/v1/auth/login' && init?.method === 'POST')
      return { status: 200, body: { access_token: 'tok' } }
    if (url === '/api/v1/me') return { status: 200, body: ME }
  })
  renderAt(<Routed />, '/login')
  await fillAndSubmit('a good password')

  expect(await screen.findByText('Welcome, Asha')).toBeInTheDocument()
  const login = fetchMock.mock.calls.find(([url]) => url === '/api/v1/auth/login')
  expect(JSON.parse(String(login?.[1]?.body))).toEqual({
    email: 'owner@example.com',
    password: 'a good password',
  })
})

it('shows a generic message when the credentials are wrong', async () => {
  mockApi((url) => {
    if (url === '/api/v1/auth/refresh') return { status: 401 }
    if (url === '/api/v1/auth/login')
      return {
        status: 401,
        body: { error: { code: 'unauthorized', message: 'Invalid email or password' } },
      }
  })
  renderAt(<Routed />, '/login')
  await fillAndSubmit('wrong password')

  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
  expect(screen.queryByText('Welcome, Asha')).not.toBeInTheDocument()
})
