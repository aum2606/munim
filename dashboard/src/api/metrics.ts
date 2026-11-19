import { useQuery } from '@tanstack/react-query'

import { api } from './client'

export interface UsageRow {
  agent: string
  model: string | null
  calls: number
  errors: number
  prompt_tokens: number
  completion_tokens: number
  cost_micros: number
  p50_ms: number
  p95_ms: number
}

export interface Overview {
  days: number
  customer_messages: number
  ai_replies: number
  staff_replies: number
  conversations_needing_a_person: number
  open_knowledge_gaps: number
  leads_by_stage: Record<string, number>
  quotes_by_status: Record<string, number>
  accepted_value_paise: number
  turns: number
  cost_micros: number
  cost_per_turn_micros: number
  unpriced_calls: number
  first_response_p50_ms: number | null
  first_response_p95_ms: number | null
  usage: UsageRow[]
}

export function useOverview(days: number) {
  return useQuery({
    queryKey: ['metrics', days],
    queryFn: () => api<Overview>(`/metrics/overview?days=${days}`),
  })
}
