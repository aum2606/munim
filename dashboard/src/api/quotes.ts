import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'

export type QuoteStatus = 'pending_approval' | 'sent' | 'accepted' | 'rejected' | 'expired'

export interface QuoteSummary {
  id: string
  quote_number: string
  status: QuoteStatus
  total_paise: number
  valid_until: string
  customer_name: string | null
  unpriced_lines: number
  created_at: string
}

export interface QuoteLine {
  id: string
  position: number
  description: string
  qty: string
  unit: string
  unit_price_paise: number
  discount_paise: number
  gst_rate: number
  hsn_sac: string | null
  line_total_paise: number
  needs_owner_pricing: boolean
}

export interface QuoteDetail {
  id: string
  quote_number: string
  status: QuoteStatus
  customer_name: string | null
  valid_until: string
  buyer_state_code: string | null
  subtotal_paise: number
  discount_paise: number
  cgst_paise: number
  sgst_paise: number
  igst_paise: number
  round_off_paise: number
  total_paise: number
  items: QuoteLine[]
  tax_groups: {
    gst_rate: number
    taxable_paise: number
    cgst_paise: number
    sgst_paise: number
    igst_paise: number
  }[]
  sent_at: string | null
}

export interface LineEdit {
  id: string
  qty?: string
  unit_price_paise?: number
  discount_paise?: number
}

export function useQuotes(status: QuoteStatus | '') {
  return useQuery({
    queryKey: ['quotes', status],
    queryFn: () => api<QuoteSummary[]>(`/quotes${status ? `?status=${status}` : ''}`),
  })
}

export function useQuote(id: string | undefined) {
  return useQuery({
    queryKey: ['quote', id],
    enabled: id !== undefined,
    queryFn: () => api<QuoteDetail>(`/quotes/${id}`),
  })
}

function useQuoteAction<T>(id: string, run: (body: T) => Promise<QuoteDetail>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: (quote) => {
      queryClient.setQueryData(['quote', id], quote)
      void queryClient.invalidateQueries({ queryKey: ['quotes'] })
      void queryClient.invalidateQueries({ queryKey: ['messages'] })
    },
  })
}

export function useEditQuote(id: string) {
  return useQuoteAction(id, (body: { items: LineEdit[]; buyer_state_code?: string | null }) =>
    api<QuoteDetail>(`/quotes/${id}`, { method: 'PATCH', body }),
  )
}

export function useQuoteTransition(id: string, action: 'approve' | 'reject' | 'mark-accepted') {
  return useQuoteAction(id, () => api<QuoteDetail>(`/quotes/${id}/${action}`, { method: 'POST' }))
}
