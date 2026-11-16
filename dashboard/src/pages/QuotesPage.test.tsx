import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'

import { setAccessToken } from '../api/client'
import type { QuoteDetail } from '../api/quotes'
import { mockApi, renderAt } from '../test/helpers'
import { QuotesPage } from './QuotesPage'

function Routed() {
  return (
    <Routes>
      <Route path="/quotes/*" element={<QuotesPage />} />
    </Routes>
  )
}

const LINE = {
  id: 'l1',
  position: 0,
  description: 'Visiting card (100 pcs)',
  qty: '5.000',
  unit: 'per 100',
  unit_price_paise: 23500,
  discount_paise: 0,
  gst_rate: 18,
  hsn_sac: '4911',
  line_total_paise: 117500,
  needs_owner_pricing: false,
}

function quote(overrides: Partial<QuoteDetail> = {}): QuoteDetail {
  return {
    id: 'q1',
    quote_number: 'Q/2026-27/0001',
    status: 'pending_approval',
    customer_name: 'Asha Traders',
    valid_until: '2026-11-22',
    buyer_state_code: null,
    subtotal_paise: 117500,
    discount_paise: 0,
    cgst_paise: 10575,
    sgst_paise: 10575,
    igst_paise: 0,
    round_off_paise: 0,
    total_paise: 138650,
    items: [LINE],
    tax_groups: [],
    sent_at: null,
    ...overrides,
  }
}

it('lists quotations with the total, status and a warning for unpriced lines', async () => {
  const fetchMock = mockApi((url) => {
    if (url.startsWith('/api/v1/quotes')) {
      return {
        status: 200,
        body: [
          {
            id: 'q1',
            quote_number: 'Q/2026-27/0001',
            status: 'pending_approval',
            total_paise: 12345678,
            valid_until: '2026-11-22',
            customer_name: 'Asha Traders',
            unpriced_lines: 2,
            created_at: '',
          },
        ],
      }
    }
  })
  renderAt(<Routed />, '/quotes')
  expect(await screen.findByText('Q/2026-27/0001')).toBeInTheDocument()
  expect(screen.getByText('₹1,23,456.78')).toBeInTheDocument()
  expect(screen.getByText('2 line(s) need a price')).toBeInTheDocument()
  expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/quotes?status=pending_approval')

  await userEvent.selectOptions(screen.getByLabelText(/Show/), 'All')
  await vi.waitFor(() => expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/v1/quotes'))
})

it('sends edited rupees as integer paise and never sends the totals', async () => {
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/quotes/q1' && init?.method === 'PATCH') {
      return { status: 200, body: quote({ total_paise: 150000 }) }
    }
    if (url === '/api/v1/quotes/q1') return { status: 200, body: quote() }
  })
  renderAt(<Routed />, '/quotes/q1')
  const rate = await screen.findByLabelText('Rate (Rs): Visiting card (100 pcs)')
  expect(rate).toHaveValue('235.00')

  await userEvent.clear(rate)
  await userEvent.type(rate, '240.50')
  await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

  const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
  expect(JSON.parse(String(patch?.[1]?.body))).toEqual({
    items: [{ id: 'l1', qty: '5.000', unit_price_paise: 24050, discount_paise: 0 }],
    buyer_state_code: null,
  })
})

it('blocks approval until every line has a price, then approves', async () => {
  let current = quote({
    items: [
      {
        ...LINE,
        id: 'l2',
        description: 'Gold plating',
        unit_price_paise: 0,
        line_total_paise: 0,
        needs_owner_pricing: true,
      },
    ],
  })
  mockApi((url, init) => {
    if (url === '/api/v1/quotes/q1/approve' && init?.method === 'POST') {
      current = quote({ status: 'sent', sent_at: '2026-11-16T10:00:00Z' })
      return { status: 200, body: current }
    }
    if (url === '/api/v1/quotes/q1') return { status: 200, body: current }
  })
  renderAt(<Routed />, '/quotes/q1')
  const approve = await screen.findByRole('button', { name: 'Approve and send to customer' })
  expect(approve).toBeDisabled()
  expect(screen.getByText('Price every line before approving.')).toBeInTheDocument()
  expect(screen.getByText('Set a price')).toBeInTheDocument()
})

it('approves a fully priced quote and then offers to mark it accepted', async () => {
  let current = quote()
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/quotes/q1/approve' && init?.method === 'POST') {
      current = quote({ status: 'sent', sent_at: '2026-11-16T10:00:00Z' })
      return { status: 200, body: current }
    }
    if (url === '/api/v1/quotes/q1') return { status: 200, body: current }
  })
  renderAt(<Routed />, '/quotes/q1')
  const approve = await screen.findByRole('button', { name: 'Approve and send to customer' })
  expect(approve).toBeEnabled()
  expect(screen.getByText('₹1,386.50')).toBeInTheDocument() // the server's total, not ours
  await userEvent.click(approve)

  expect(await screen.findByRole('button', { name: 'Mark as accepted' })).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Approve and send to customer' }),
  ).not.toBeInTheDocument()
  expect(screen.getByLabelText('Rate (Rs): Visiting card (100 pcs)')).toBeDisabled() // frozen
  expect(fetchMock.mock.calls.filter(([, i]) => i?.method === 'POST')).toHaveLength(1)
})

it('shows the server reason when an action is refused', async () => {
  mockApi((url, init) => {
    if (init?.method === 'POST') {
      return {
        status: 409,
        body: { error: { code: 'conflict', message: 'This quote has expired' } },
      }
    }
    if (url === '/api/v1/quotes/q1') return { status: 200, body: quote() }
  })
  renderAt(<Routed />, '/quotes/q1')
  await userEvent.click(await screen.findByRole('button', { name: 'Approve and send to customer' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This quote has expired')
})

it('downloads the PDF with the signed-in token rather than a bare link', async () => {
  setAccessToken('tok')
  const open = vi.fn()
  vi.stubGlobal('open', open)
  URL.createObjectURL = vi.fn(() => 'blob:pdf')
  URL.revokeObjectURL = vi.fn()
  const fetchMock = vi.fn(async (url: string) =>
    url === '/api/v1/quotes/q1'
      ? new Response(JSON.stringify(quote()), { status: 200 })
      : new Response(new Blob(['%PDF-1.4']), { status: 200 }),
  )
  vi.stubGlobal('fetch', fetchMock)
  renderAt(<Routed />, '/quotes/q1')
  await userEvent.click(await screen.findByRole('button', { name: 'Download PDF' }))
  await vi.waitFor(() => expect(open).toHaveBeenCalledWith('blob:pdf', '_blank', 'noopener'))
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/v1/quotes/q1/pdf',
    expect.objectContaining({ headers: { Authorization: 'Bearer tok' } }),
  )
})
