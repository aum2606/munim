import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import type { FollowUp } from '../api/followups'
import { mockApi, renderAt } from '../test/helpers'
import { FollowUpsPage } from './FollowUpsPage'

const DRAFT: FollowUp = {
  id: 'f1',
  conversation_id: 'c1',
  quote_number: 'Q/2026-27/0001',
  customer_name: 'Asha',
  draft: 'Just checking in on quotation Q/2026-27/0001.',
  status: 'draft',
  can_send: true,
  created_at: '',
}

it('sends an edited draft and then dismisses another', async () => {
  let drafts = [DRAFT, { ...DRAFT, id: 'f2', quote_number: 'Q/2026-27/0002' }]
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/follow-ups/f1/send' && init?.method === 'POST') {
      drafts = drafts.filter((d) => d.id !== 'f1')
      return { status: 204 }
    }
    if (url === '/api/v1/follow-ups/f2/dismiss' && init?.method === 'POST') {
      drafts = drafts.filter((d) => d.id !== 'f2')
      return { status: 204 }
    }
    if (url === '/api/v1/follow-ups?status=draft') return { status: 200, body: drafts }
  })
  renderAt(<FollowUpsPage />)

  const box = await screen.findByLabelText('Q/2026-27/0001')
  await userEvent.clear(box)
  await userEvent.type(box, 'Any update?')
  await userEvent.click(screen.getAllByRole('button', { name: 'Send' })[0]!)
  await vi.waitFor(() => expect(screen.queryByLabelText('Q/2026-27/0001')).not.toBeInTheDocument())
  const send = fetchMock.mock.calls.find(([url]) => url.endsWith('/f1/send'))
  expect(JSON.parse(String(send?.[1]?.body))).toEqual({ text: 'Any update?' })

  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
  expect(await screen.findByText('No follow-ups waiting.')).toBeInTheDocument()
})

it('offers to copy instead of send when WhatsApp would refuse the message', async () => {
  mockApi((url) => {
    if (url === '/api/v1/follow-ups?status=draft') {
      return { status: 200, body: [{ ...DRAFT, can_send: false }] }
    }
  })
  renderAt(<FollowUpsPage />)
  expect(await screen.findByRole('button', { name: 'Copy text' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent('24 hours')
})
