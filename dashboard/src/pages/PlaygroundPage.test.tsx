import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import { mockApi, renderAt } from '../test/helpers'
import { PlaygroundPage } from './PlaygroundPage'

const CUSTOMER = {
  id: 'm1',
  direction: 'in',
  sender_type: 'customer',
  content: 'visiting card ka rate?',
  language: null,
  intent: null,
  reply_to_id: null,
  created_at: '',
}
const REPLY = {
  id: 'm2',
  direction: 'out',
  sender_type: 'ai',
  content: 'Visiting card: ₹250.00 per 100 + 18% GST',
  language: 'hinglish',
  intent: 'pricing',
  reply_to_id: 'm1',
  created_at: '',
}

it('sends a message, waits for the assistant, and shows how the reply was made', async () => {
  let fetches = 0
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/playground/messages' && init?.method === 'POST') {
      return { status: 202, body: { conversation_id: 'c1', message_id: 'm1' } }
    }
    if (url === '/api/v1/conversations/c1/messages') {
      // the first look finds only the customer's message; the reply arrives a moment later
      return { status: 200, body: ++fetches < 2 ? [CUSTOMER] : [CUSTOMER, REPLY] }
    }
    if (url === '/api/v1/agent-runs?message_id=m1') {
      return {
        status: 200,
        body: [
          {
            id: 'r1',
            agent: 'router',
            provider: 'fake',
            model: 'fake-1',
            prompt_version: 'router@abc',
            output: { intent: 'pricing' },
            tool_calls: [],
            latency_ms: 12,
            prompt_tokens: 10,
            completion_tokens: 5,
            status: 'ok',
            error: null,
          },
          {
            id: 'r2',
            agent: 'knowledge',
            provider: 'fake',
            model: 'fake-1',
            prompt_version: 'knowledge@def',
            output: { grounded: true },
            tool_calls: [{ tool: 'lookup_catalog', args: ['terms'], results: 1 }],
            latency_ms: 30,
            prompt_tokens: 100,
            completion_tokens: 20,
            status: 'ok',
            error: null,
          },
        ],
      }
    }
  })
  renderAt(<PlaygroundPage />)

  await userEvent.type(screen.getByLabelText('Type a customer message'), 'visiting card ka rate?')
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))

  expect(await screen.findByText('Assistant is typing…')).toBeInTheDocument()
  const reply = await screen.findByText(/₹250.00 per 100/, {}, { timeout: 5000 })
  const post = fetchMock.mock.calls.find(([url]) => url === '/api/v1/playground/messages')
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    conversation_id: null,
    text: 'visiting card ka rate?',
  })
  expect(screen.queryByText('Assistant is typing…')).not.toBeInTheDocument()

  await userEvent.click(reply)
  expect(await screen.findByText('router')).toBeInTheDocument()
  expect(screen.getByText('knowledge')).toBeInTheDocument()
  expect(screen.getByText('tools: lookup_catalog')).toBeInTheDocument()
  expect(screen.getByText('knowledge@def')).toBeInTheDocument()
})

it('renders model output as plain text, never as markup', async () => {
  const hostile = { ...REPLY, content: '<img src=x onerror=alert(1)> <b>bold</b>' }
  mockApi((url, init) => {
    if (url === '/api/v1/playground/messages' && init?.method === 'POST') {
      return { status: 202, body: { conversation_id: 'c1', message_id: 'm1' } }
    }
    if (url === '/api/v1/conversations/c1/messages')
      return { status: 200, body: [CUSTOMER, hostile] }
  })
  const { container } = renderAt(<PlaygroundPage />)
  await userEvent.type(screen.getByLabelText('Type a customer message'), 'hi')
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))

  expect(await screen.findByText(/<img src=x/)).toBeInTheDocument()
  expect(container.querySelector('img')).toBeNull()
  expect(container.querySelector('b')).toBeNull()
})

it('starts a fresh conversation with the new chat button', async () => {
  mockApi((url, init) => {
    if (url === '/api/v1/playground/messages' && init?.method === 'POST') {
      return { status: 202, body: { conversation_id: 'c1', message_id: 'm1' } }
    }
    if (url === '/api/v1/conversations/c1/messages') return { status: 200, body: [CUSTOMER, REPLY] }
  })
  renderAt(<PlaygroundPage />)
  await userEvent.type(screen.getByLabelText('Type a customer message'), 'hi')
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  await screen.findByText(/₹250.00/)
  await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
  expect(screen.queryByText(/₹250.00/)).not.toBeInTheDocument()
})
