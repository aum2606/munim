import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { expect, it } from 'vitest'

import type { ChatMessage, Conversation } from '../api/chat'
import { mockApi, renderAt } from '../test/helpers'
import { InboxPage } from './InboxPage'

function Routed() {
  return (
    <Routes>
      <Route path="/inbox/*" element={<InboxPage />} />
    </Routes>
  )
}

const CONVERSATION: Conversation = {
  id: 'c1',
  channel: 'whatsapp',
  mode: 'ai',
  customer_name: 'Asha',
  customer_phone: '+919876543210',
  last_message: 'rate kya hai?',
  can_reply: true,
  last_customer_msg_at: null,
  last_business_msg_at: null,
  created_at: '',
}

const message = (overrides: Partial<ChatMessage>): ChatMessage => ({
  id: 'm1',
  direction: 'in',
  sender_type: 'customer',
  content: 'hello',
  language: null,
  intent: null,
  reply_to_id: null,
  quote_id: null,
  kind: 'text',
  transcript_confidence: null,
  delivery_status: null,
  delivery_error: null,
  created_at: '',
  ...overrides,
})

it('lists conversations with the customer, a preview and who is in charge', async () => {
  mockApi((url) => {
    if (url === '/api/v1/conversations') {
      return {
        status: 200,
        body: [CONVERSATION, { ...CONVERSATION, id: 'c2', customer_name: null, mode: 'human' }],
      }
    }
  })
  renderAt(<Routed />, '/inbox')
  expect(await screen.findByText('Asha')).toBeInTheDocument()
  expect(screen.getAllByText('rate kya hai?')).toHaveLength(2)
  expect(screen.getByText('+919876543210')).toBeInTheDocument() // no name: the number
  expect(screen.getByText('Needs a person')).toBeInTheDocument()
})

it('takes a chat over and then sends a reply', async () => {
  let mode: 'ai' | 'human' = 'ai'
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/conversations/c1/take-over' && init?.method === 'POST') {
      mode = 'human'
      return { status: 204 }
    }
    if (url === '/api/v1/conversations/c1/replies' && init?.method === 'POST') {
      return { status: 201, body: message({ id: 'm2', direction: 'out', content: 'Hi Asha' }) }
    }
    if (url === '/api/v1/conversations') return { status: 200, body: [{ ...CONVERSATION, mode }] }
    if (url === '/api/v1/conversations/c1/messages') return { status: 200, body: [message({})] }
  })
  renderAt(<Routed />, '/inbox/c1')

  await userEvent.click(await screen.findByRole('button', { name: 'Take over' }))
  expect(await screen.findByRole('button', { name: 'Hand back to AI' })).toBeInTheDocument()
  expect(screen.getByText(/The assistant stays silent/)).toBeInTheDocument()

  await userEvent.type(screen.getByLabelText('Your reply'), 'Hi Asha')
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  const reply = fetchMock.mock.calls.find(([url]) => url.endsWith('/replies'))
  expect(JSON.parse(String(reply?.[1]?.body))).toEqual({ text: 'Hi Asha' })
  expect(screen.getByLabelText('Your reply')).toHaveValue('') // cleared once sent
})

it('hides the reply box and explains why when WhatsApp would refuse the message', async () => {
  mockApi((url) => {
    if (url === '/api/v1/conversations') {
      return { status: 200, body: [{ ...CONVERSATION, can_reply: false }] }
    }
    if (url === '/api/v1/conversations/c1/messages') return { status: 200, body: [message({})] }
  })
  renderAt(<Routed />, '/inbox/c1')
  expect(await screen.findByRole('note')).toHaveTextContent('24 hours')
  expect(screen.queryByLabelText('Your reply')).not.toBeInTheDocument()
})

it('shows voice notes as what was heard and how each reply was delivered', async () => {
  mockApi((url) => {
    if (url === '/api/v1/conversations') return { status: 200, body: [CONVERSATION] }
    if (url === '/api/v1/conversations/c1/messages') {
      return {
        status: 200,
        body: [
          message({ kind: 'audio', content: 'five hundred cards', transcript_confidence: 0.4 }),
          message({ id: 'm2', direction: 'out', content: 'Sure', delivery_status: 'read' }),
          message({
            id: 'm3',
            direction: 'out',
            content: 'Late',
            delivery_status: 'window_closed',
          }),
        ],
      }
    }
  })
  renderAt(<Routed />, '/inbox/c1')
  expect(await screen.findByText(/Voice note/)).toBeInTheDocument()
  expect(screen.getByText('five hundred cards', { exact: false })).toBeInTheDocument()
  expect(screen.getByText('Read')).toBeInTheDocument()
  expect(screen.getByText('Not sent: 24-hour window closed')).toBeInTheDocument()
})

it('shows the server reason when a reply is refused', async () => {
  mockApi((url, init) => {
    if (init?.method === 'POST') {
      return { status: 409, body: { error: { code: 'conflict', message: 'Window is closed' } } }
    }
    if (url === '/api/v1/conversations') return { status: 200, body: [CONVERSATION] }
    if (url === '/api/v1/conversations/c1/messages') return { status: 200, body: [] }
  })
  renderAt(<Routed />, '/inbox/c1')
  await userEvent.type(await screen.findByLabelText('Your reply'), 'Hello')
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Window is closed')
})
