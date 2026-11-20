import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, refreshSession, setAccessToken, type Me } from './client'

const SESSION_KEY = ['session']

export interface LoginInput {
  email: string
  password: string
}

export interface RegisterInput extends LoginInput {
  business_name: string
  business_type: string
  name: string
}

/** The signed-in user, or null. On first load the refresh cookie restores the session. */
export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: async (): Promise<Me | null> => ((await refreshSession()) ? api<Me>('/me') : null),
    staleTime: Infinity,
    retry: false,
  })
}

async function startSession(path: string, body: unknown): Promise<Me> {
  const token = await api<{ access_token: string }>(path, { method: 'POST', body })
  setAccessToken(token.access_token)
  return api<Me>('/me')
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: LoginInput) => startSession('/auth/login', input),
    onSuccess: (me) => queryClient.setQueryData(SESSION_KEY, me),
  })
}

export function useRegister() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: RegisterInput) => startSession('/auth/register', input),
    onSuccess: (me) => queryClient.setQueryData(SESSION_KEY, me),
  })
}

export function useForgotPassword() {
  return useMutation({
    mutationFn: (email: string) =>
      api<{ detail: string }>('/auth/forgot-password', { method: 'POST', body: { email } }),
  })
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (input: { token: string; password: string }) =>
      api<void>('/auth/reset-password', { method: 'POST', body: input }),
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      setAccessToken(null)
      queryClient.clear() // drop every cached tenant's data with the session
      queryClient.setQueryData(SESSION_KEY, null)
    },
  })
}
