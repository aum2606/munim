import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'

export interface FollowUp {
  id: string
  conversation_id: string
  quote_number: string | null
  customer_name: string | null
  draft: string
  status: 'draft' | 'sent' | 'dismissed'
  can_send: boolean
  created_at: string
}

export function useFollowUps() {
  return useQuery({
    queryKey: ['follow-ups'],
    queryFn: () => api<FollowUp[]>('/follow-ups?status=draft'),
  })
}

export function useFollowUpActions(id: string) {
  const queryClient = useQueryClient()
  const done = () => queryClient.invalidateQueries({ queryKey: ['follow-ups'] })
  return {
    send: useMutation({
      mutationFn: (text: string) =>
        api<void>(`/follow-ups/${id}/send`, { method: 'POST', body: { text } }),
      onSuccess: done,
    }),
    dismiss: useMutation({
      mutationFn: () => api<void>(`/follow-ups/${id}/dismiss`, { method: 'POST' }),
      onSuccess: done,
    }),
  }
}
