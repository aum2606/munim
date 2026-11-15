import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { expect, it } from 'vitest'

import { ME, mockApi, renderAt } from '../test/helpers'
import { ProtectedRoute } from './ProtectedRoute'

function Routed() {
  return (
    <Routes>
      <Route path="/login" element={<p>login screen</p>} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<p>secret page</p>} />
      </Route>
    </Routes>
  )
}

it('sends a signed-out visitor to the login page', async () => {
  mockApi((url) => (url === '/api/v1/auth/refresh' ? { status: 401 } : undefined))
  renderAt(<Routed />)
  expect(await screen.findByText('login screen')).toBeInTheDocument()
  expect(screen.queryByText('secret page')).not.toBeInTheDocument()
})

it('restores the session from the refresh cookie and shows the page', async () => {
  mockApi((url) => {
    if (url === '/api/v1/auth/refresh') return { status: 200, body: { access_token: 'tok' } }
    if (url === '/api/v1/me') return { status: 200, body: ME }
  })
  renderAt(<Routed />)
  expect(await screen.findByText('secret page')).toBeInTheDocument()
})
