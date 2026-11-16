import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'

export interface Profile {
  id: string
  name: string
  business_type: string
  gstin: string | null
  state_code: string | null
  address: string | null
  phone: string | null
  quote_terms: string | null
  quote_validity_days: number
}

export type ProfileUpdate = Partial<Omit<Profile, 'id' | 'state_code'>>

export function useProfile() {
  return useQuery({ queryKey: ['profile'], queryFn: () => api<Profile>('/tenant') })
}

export function useSaveProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ProfileUpdate) => api<Profile>('/tenant', { method: 'PUT', body }),
    onSuccess: (profile) => {
      queryClient.setQueryData(['profile'], profile)
      void queryClient.invalidateQueries({ queryKey: ['session'] })
    },
  })
}
