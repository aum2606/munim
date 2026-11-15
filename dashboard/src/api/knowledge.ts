import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'

export interface CatalogItem {
  id: string
  sku: string
  name: string
  aliases: string[]
  category: string | null
  description: string | null
  unit: string
  base_price_paise: number
  gst_rate: number
  hsn_sac: string | null
  stock_status: string
  is_active: boolean
}

export interface ImportRow {
  row: number
  values: Record<string, unknown>
  errors: string[]
}

export interface ImportPreview {
  job_id: string
  filename: string
  status: string
  headers: string[]
  mapping: Record<string, string>
  missing_required: string[]
  row_count: number
  valid_count: number
  error_count: number
  rows: ImportRow[]
}

export interface ImportResult {
  created: number
  updated: number
  skipped: number
}

export interface KnowledgeDocument {
  id: string
  title: string
  source_type: string
  status: 'pending' | 'processing' | 'ready' | 'failed'
  error: string | null
  created_at: string
}

export interface Faq {
  id: string
  question: string
  answer: string
  status: string
}

export interface Gap {
  id: string
  question: string
  occurrences: number
  status: 'open' | 'answered' | 'ignored'
  answer_text: string | null
  created_at: string
}

export const CATALOG_FIELDS = [
  'sku',
  'name',
  'aliases',
  'category',
  'description',
  'unit',
  'price',
  'gst_rate',
  'hsn_sac',
  'stock_status',
] as const

export function useCatalogItems(q: string) {
  return useQuery({
    queryKey: ['catalog', q],
    queryFn: () => api<CatalogItem[]>(`/catalog/items?limit=200&q=${encodeURIComponent(q)}`),
  })
}

export function useDeleteItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/catalog/items/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog'] }),
  })
}

export function useStartImport() {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api<ImportPreview>('/catalog/import', { method: 'POST', body: form })
    },
  })
}

export function useSetMapping(jobId: string) {
  return useMutation({
    mutationFn: (mapping: Record<string, string>) =>
      api<ImportPreview>(`/catalog/import/${jobId}`, { method: 'PATCH', body: { mapping } }),
  })
}

export function useCommitImport(jobId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api<ImportResult>(`/catalog/import/${jobId}/commit`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog'] }),
  })
}

export function useDocuments() {
  return useQuery({
    queryKey: ['documents'],
    queryFn: () => api<KnowledgeDocument[]>('/documents'),
    // keep polling while the worker is still reading or embedding a file
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === 'pending' || d.status === 'processing')
        ? 3000
        : false,
  })
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, title }: { file: File; title: string }) => {
      const form = new FormData()
      form.append('file', file)
      if (title) form.append('title', title)
      return api<KnowledgeDocument>('/documents', { method: 'POST', body: form })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })
}

export function useDeleteDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/documents/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })
}

export function useFaqs() {
  return useQuery({ queryKey: ['faqs'], queryFn: () => api<Faq[]>('/faqs') })
}

export function useSaveFaq() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, question, answer }: { id?: string; question: string; answer: string }) =>
      id
        ? api<Faq>(`/faqs/${id}`, { method: 'PUT', body: { question, answer } })
        : api<Faq>('/faqs', { method: 'POST', body: { question, answer } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['faqs'] }),
  })
}

export function useDeleteFaq() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/faqs/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['faqs'] }),
  })
}

export function useGaps() {
  return useQuery({
    queryKey: ['gaps'],
    queryFn: () => api<Gap[]>('/knowledge-gaps?status=open'),
  })
}

export function useResolveGap() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string | null }) =>
      answer === null
        ? api<Gap>(`/knowledge-gaps/${id}/ignore`, { method: 'POST' })
        : api<Gap>(`/knowledge-gaps/${id}/answer`, { method: 'POST', body: { answer } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['gaps'] })
      void queryClient.invalidateQueries({ queryKey: ['faqs'] })
    },
  })
}
