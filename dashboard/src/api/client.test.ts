import { expect, it } from 'vitest'

import { mockApi } from '../test/helpers'
import { api, ApiError, setAccessToken } from './client'

it('sends the access token as a bearer header', async () => {
  const fetchMock = mockApi(() => ({ status: 200, body: { ok: true } }))
  setAccessToken('abc')
  await api('/me')
  const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>
  expect(headers.Authorization).toBe('Bearer abc')
})

it('refreshes once on a 401 and replays the request with the new token', async () => {
  let meCalls = 0
  const fetchMock = mockApi((url) => {
    if (url === '/api/v1/auth/refresh') return { status: 200, body: { access_token: 'fresh' } }
    if (url === '/api/v1/me')
      return ++meCalls === 1 ? { status: 401 } : { status: 200, body: { ok: 1 } }
  })
  setAccessToken('expired')
  expect(await api('/me')).toEqual({ ok: 1 })
  const replay = fetchMock.mock.calls.at(-1)?.[1]?.headers as Record<string, string>
  expect(replay.Authorization).toBe('Bearer fresh')
})

it('gives up (and does not loop) when the refresh fails', async () => {
  const fetchMock = mockApi(() => ({ status: 401 }))
  await expect(api('/me')).rejects.toBeInstanceOf(ApiError)
  expect(fetchMock).toHaveBeenCalledTimes(2) // the request, then one refresh attempt
})

it('does not try to refresh when a login attempt itself is rejected', async () => {
  const fetchMock = mockApi(() => ({
    status: 401,
    body: { error: { code: 'unauthorized', message: 'Invalid email or password' } },
  }))
  await expect(api('/auth/login', { method: 'POST', body: {} })).rejects.toMatchObject({
    status: 401,
    message: 'Invalid email or password',
  })
  expect(fetchMock).toHaveBeenCalledTimes(1)
})
