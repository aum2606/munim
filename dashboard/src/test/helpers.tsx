import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import type { Me } from '../api/client'

export const ME: Me = {
  user: { id: 'u1', email: 'owner@example.com', name: 'Asha', role: 'owner', is_active: true },
  tenant: { id: 't1', name: 'Asha Press', business_type: 'printing', timezone: 'Asia/Kolkata' },
}

type Route = (url: string, init?: RequestInit) => { status: number; body?: unknown } | undefined

/** Replace fetch with a router of fake API answers. Unrouted requests fail the test. */
export function mockApi(route: Route) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const answer = route(url, init)
    if (!answer) throw new Error(`unexpected request: ${init?.method ?? 'GET'} ${url}`)
    return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
      status: answer.status,
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export function renderAt(ui: ReactElement, path = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}
