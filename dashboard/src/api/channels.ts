import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'

export interface WhatsAppStatus {
  connected: boolean
  phone_number_id: string | null
  display_phone: string | null
  webhook_ready: boolean
}

export interface WhatsAppConnect {
  phone_number_id: string
  display_phone: string | null
  access_token: string
}

export function useWhatsAppStatus() {
  return useQuery({
    queryKey: ['whatsapp'],
    queryFn: () => api<WhatsAppStatus>('/channels/whatsapp'),
  })
}

export function useWhatsAppConnection() {
  const queryClient = useQueryClient()
  const done = () => queryClient.invalidateQueries({ queryKey: ['whatsapp'] })
  return {
    connect: useMutation({
      mutationFn: (body: WhatsAppConnect) =>
        api<WhatsAppStatus>('/channels/whatsapp', { method: 'PUT', body }),
      onSuccess: done,
    }),
    disconnect: useMutation({
      mutationFn: () => api<void>('/channels/whatsapp', { method: 'DELETE' }),
      onSuccess: done,
    }),
  }
}
