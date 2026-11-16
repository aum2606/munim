import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'

export interface ChatMessage {
  id: string
  direction: 'in' | 'out'
  sender_type: 'customer' | 'ai' | 'staff' | 'system'
  content: string
  language: string | null
  intent: string | null
  reply_to_id: string | null
  quote_id: string | null
  kind: 'text' | 'audio'
  transcript_confidence: number | null
  delivery_status: 'sent' | 'delivered' | 'read' | 'failed' | 'window_closed' | null
  delivery_error: string | null
  created_at: string
}

export interface Conversation {
  id: string
  channel: string
  mode: 'ai' | 'human'
  customer_name: string | null
  customer_phone: string | null
  last_message: string | null
  can_reply: boolean
  last_customer_msg_at: string | null
  last_business_msg_at: string | null
  created_at: string
}

export interface AgentRun {
  id: string
  agent: string
  provider: string | null
  model: string | null
  prompt_version: string
  output: Record<string, unknown> | null
  tool_calls: { tool: string; args: string[]; results: number | null }[]
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  status: 'ok' | 'error'
  error: string | null
}

export function useConversationMessages(conversationId: string | null) {
  return useQuery({
    queryKey: ['messages', conversationId],
    enabled: conversationId !== null,
    queryFn: () => api<ChatMessage[]>(`/conversations/${conversationId}/messages`),
    // Quick while the customer is waiting for a reply; slower otherwise, so a live chat stays live.
    refetchInterval: (query) => (query.state.data?.at(-1)?.direction === 'in' ? 1500 : 5000),
  })
}

export function useSendPlayground() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { conversationId: string | null; text: string }) =>
      api<{ conversation_id: string; message_id: string }>('/playground/messages', {
        method: 'POST',
        body: { conversation_id: input.conversationId, text: input.text },
      }),
    onSuccess: (sent) =>
      queryClient.invalidateQueries({ queryKey: ['messages', sent.conversation_id] }),
  })
}

export function useAgentRuns(messageId: string | null) {
  return useQuery({
    queryKey: ['agent-runs', messageId],
    enabled: messageId !== null,
    queryFn: () => api<AgentRun[]>(`/agent-runs?message_id=${messageId}`),
  })
}

export function useConversations() {
  return useQuery({
    queryKey: ['conversations'],
    queryFn: () => api<Conversation[]>('/conversations'),
    refetchInterval: 10000,
  })
}

/** Take over, hand back, or reply in one conversation. Each refreshes the inbox. */
export function useConversationActions(conversationId: string) {
  const queryClient = useQueryClient()
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    void queryClient.invalidateQueries({ queryKey: ['messages', conversationId] })
  }
  const base = `/conversations/${conversationId}`
  return {
    takeOver: useMutation({
      mutationFn: () => api<void>(`${base}/take-over`, { method: 'POST' }),
      onSuccess: refresh,
    }),
    returnToAi: useMutation({
      mutationFn: () => api<void>(`${base}/return-to-ai`, { method: 'POST' }),
      onSuccess: refresh,
    }),
    reply: useMutation({
      mutationFn: (text: string) =>
        api<ChatMessage>(`${base}/replies`, { method: 'POST', body: { text } }),
      onSuccess: refresh,
    }),
  }
}
