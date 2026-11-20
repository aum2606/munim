import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import type { Overview } from '../api/metrics'
import { mockApi, renderAt } from '../test/helpers'
import { MetricsPage } from './MetricsPage'

const OVERVIEW: Overview = {
  days: 7,
  customer_messages: 42,
  ai_replies: 38,
  staff_replies: 3,
  conversations_needing_a_person: 2,
  open_knowledge_gaps: 5,
  leads_by_stage: { new: 4, quoted: 2 },
  quotes_by_status: { accepted: 1 },
  accepted_value_paise: 12345678,
  model_calls_24h: 120,
  model_call_budget: 600,
  turns: 40,
  cost_micros: 8000,
  cost_per_turn_micros: 200,
  unpriced_calls: 3,
  first_response_p50_ms: 2500,
  first_response_p95_ms: 6100,
  usage: [
    {
      agent: 'knowledge',
      model: 'openai/gpt-oss-120b',
      calls: 30,
      errors: 1,
      prompt_tokens: 60000,
      completion_tokens: 9000,
      cost_micros: 7000,
      p50_ms: 900,
      p95_ms: 2100,
    },
  ],
}

it('shows the numbers, with money in rupees and cost in dollars, and says what it could not price', async () => {
  mockApi((url) => {
    if (url === '/api/v1/metrics/overview?days=7') return { status: 200, body: OVERVIEW }
  })
  renderAt(<MetricsPage />)
  expect(await screen.findByText('42')).toBeInTheDocument()
  expect(screen.getByText('₹1,23,456.78')).toBeInTheDocument() // from paise, lakh grouping
  expect(screen.getByText('$0.0002')).toBeInTheDocument() // cost per message
  expect(screen.getByText('2.5 s')).toBeInTheDocument()
  expect(screen.getByText('6.1 s')).toBeInTheDocument()
  expect(screen.getByText('120')).toBeInTheDocument() // model calls in the last day
  expect(screen.getByText(/of 600 a day/)).toBeInTheDocument()
  expect(screen.getByText('openai/gpt-oss-120b')).toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent('3 model calls')
})

it('reloads for another period', async () => {
  const fetchMock = mockApi((url) => {
    if (url.startsWith('/api/v1/metrics/overview')) {
      return { status: 200, body: { ...OVERVIEW, usage: [], unpriced_calls: 0 } }
    }
  })
  renderAt(<MetricsPage />)
  await screen.findByText('42')
  await userEvent.selectOptions(screen.getByLabelText(/Period/), 'Last 30 days')
  await screen.findByText('42')
  expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/v1/metrics/overview?days=30')
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

it('shows the reason when the server refuses', async () => {
  mockApi(() => ({
    status: 403,
    body: { error: { code: 'forbidden', message: 'Owner access required' } },
  }))
  renderAt(<MetricsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Owner access required')
})
