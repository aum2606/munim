import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { expect, it } from 'vitest'

import { mockApi, renderAt } from '../test/helpers'
import { KnowledgePage } from './KnowledgePage'

function Routed() {
  return (
    <Routes>
      <Route path="/knowledge/*" element={<KnowledgePage />} />
    </Routes>
  )
}

it('shows catalogue prices with lakh grouping, from integer paise', async () => {
  mockApi((url) => {
    if (url.startsWith('/api/v1/catalog/items')) {
      return {
        status: 200,
        body: [
          {
            id: '1',
            sku: 'VC',
            name: 'Visiting card',
            base_price_paise: 25000,
            unit: 'per 100',
            gst_rate: 18,
            category: 'Cards',
          },
          {
            id: '2',
            sku: 'ALB',
            name: 'Premium album',
            base_price_paise: 12345678,
            unit: 'each',
            gst_rate: 18,
            category: null,
          },
        ],
      }
    }
  })
  renderAt(<Routed />, '/knowledge/catalogue')
  expect(await screen.findByText('₹250.00')).toBeInTheDocument()
  expect(screen.getByText('₹1,23,456.78')).toBeInTheDocument()
  expect(screen.getByText('Prices exclude GST')).toBeInTheDocument()
})

it('shows an empty-state hint when there are no items', async () => {
  mockApi((url) =>
    url.startsWith('/api/v1/catalog/items') ? { status: 200, body: [] } : undefined,
  )
  renderAt(<Routed />, '/knowledge/catalogue')
  expect(await screen.findByText(/No items yet/)).toBeInTheDocument()
})

it('answers a knowledge gap and sends the answer to the server', async () => {
  const gaps = [
    {
      id: 'g1',
      question: 'Do you do lamination?',
      occurrences: 7,
      status: 'open',
      answer_text: null,
      created_at: '',
    },
  ]
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/knowledge-gaps?status=open') return { status: 200, body: gaps }
    if (url === '/api/v1/knowledge-gaps/g1/answer' && init?.method === 'POST') {
      gaps.pop() // answered gaps leave the open list
      return { status: 200, body: { ...gaps[0], status: 'answered' } }
    }
    if (url === '/api/v1/faqs') return { status: 200, body: [] }
  })
  renderAt(<Routed />, '/knowledge/gaps')

  expect(await screen.findByText('Do you do lamination?')).toBeInTheDocument()
  expect(screen.getByText('Asked 7 time(s)')).toBeInTheDocument()
  const save = screen.getByRole('button', { name: 'Answer and add to FAQs' })
  expect(save).toBeDisabled() // nothing to send yet

  await userEvent.type(screen.getByLabelText(/Your answer/), 'Yes, matt and gloss.')
  await userEvent.click(save)

  expect(await screen.findByText(/No open gaps/)).toBeInTheDocument()
  const post = fetchMock.mock.calls.find(([url]) => url.endsWith('/g1/answer'))
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({ answer: 'Yes, matt and gloss.' })
})

it('creates an FAQ from the form', async () => {
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/faqs' && init?.method === 'POST') {
      return { status: 201, body: { id: 'f1', question: 'Q', answer: 'A', status: 'pending' } }
    }
    if (url === '/api/v1/faqs') return { status: 200, body: [] }
  })
  renderAt(<Routed />, '/knowledge/faqs')
  await userEvent.type(await screen.findByLabelText('Question'), 'Do you deliver?')
  await userEvent.type(screen.getByLabelText('Answer'), 'Yes, in Surat.')
  await userEvent.click(screen.getByRole('button', { name: 'Save FAQ' }))
  await screen.findByText(/No FAQs yet/)
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    question: 'Do you deliver?',
    answer: 'Yes, in Surat.',
  })
})
