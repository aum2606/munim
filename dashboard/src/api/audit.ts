import { useQuery } from '@tanstack/react-query'

import { api } from './client'

export interface AuditEvent {
  id: string
  created_at: string
  action: string
  target: string | null
  actor: string | null
}

export function useAuditLog() {
  return useQuery({
    queryKey: ['audit'],
    queryFn: () => api<AuditEvent[]>('/audit'),
    retry: false, // staff get a 403: show nothing rather than keep asking
  })
}
