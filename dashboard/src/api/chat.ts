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
  created_at: string
}

export interface Conversation {
  id: string
  channel: string
  mode: 'ai' | 'human'
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
    // Poll only while the customer is waiting: the last message is theirs, with no reply yet.
    refetchInterval: (query) => (query.state.data?.at(-1)?.direction === 'in' ? 1500 : false),
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
  })
}
