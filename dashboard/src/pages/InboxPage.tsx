import { useState, type FormEvent } from 'react'
import { Link, Route, Routes, useParams } from 'react-router-dom'

import {
  useConversationActions,
  useConversationMessages,
  useConversations,
  type ChatMessage,
  type Conversation,
} from '../api/chat'
import { t, type MessageKey } from '../i18n/en'

export function InboxPage() {
  return (
    <Routes>
      <Route index element={<ConversationList />} />
      <Route path=":conversationId" element={<ConversationView />} />
    </Routes>
  )
}

function ModeBadge({ mode }: { mode: Conversation['mode'] }) {
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
        mode === 'human' ? 'bg-amber-100 text-amber-800' : 'bg-green-100 text-green-800'
      }`}
    >
      {t(mode === 'human' ? 'inbox.mode.human' : 'inbox.mode.ai')}
    </span>
  )
}

const who = (c: Conversation) => c.customer_name ?? c.customer_phone ?? t('inbox.customer')

function ConversationList() {
  const conversations = useConversations()
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">{t('inbox.title')}</h1>
      {conversations.data?.length === 0 && <p className="text-slate-500">{t('inbox.empty')}</p>}
      <ul className="space-y-2">
        {conversations.data?.map((conversation) => (
          <li key={conversation.id}>
            <Link
              to={conversation.id}
              className="flex items-center justify-between gap-3 rounded-lg bg-white p-3 shadow-sm"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{who(conversation)}</span>
                <span className="block truncate text-sm text-slate-500">
                  {conversation.last_message ?? conversation.channel}
                </span>
              </span>
              <ModeBadge mode={conversation.mode} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Delivery({ message }: { message: ChatMessage }) {
  if (message.direction === 'in' || message.delivery_status === null) return null
  const bad = message.delivery_status === 'failed' || message.delivery_status === 'window_closed'
  return (
    <span className={`mt-1 block text-xs ${bad ? 'text-red-600' : 'text-slate-500'}`}>
      {t(`inbox.delivery.${message.delivery_status}` as MessageKey)}
    </span>
  )
}

function Bubble({ message }: { message: ChatMessage }) {
  const incoming = message.direction === 'in'
  return (
    <li
      className={`w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 ${
        incoming ? 'ml-auto bg-indigo-600 text-white' : 'bg-slate-100'
      }`}
    >
      {message.kind === 'audio' && (
        <span className="mb-1 block text-xs opacity-80">
          {t('inbox.voice')} · {t('inbox.heardAs')}
        </span>
      )}
      {message.content}
      <Delivery message={message} />
    </li>
  )
}

function ConversationView() {
  const { conversationId = '' } = useParams()
  const messages = useConversationMessages(conversationId)
  const conversations = useConversations()
  const conversation = conversations.data?.find((c) => c.id === conversationId)
  const actions = useConversationActions(conversationId)
  const [text, setText] = useState('')

  const send = (event: FormEvent) => {
    event.preventDefault()
    if (!text.trim()) return
    actions.reply.mutate(text.trim(), { onSuccess: () => setText('') })
  }

  const human = conversation?.mode === 'human'
  const error = actions.reply.error ?? actions.takeOver.error ?? actions.returnToAi.error
  return (
    <div className="space-y-3">
      <Link to="/inbox" className="text-sm text-indigo-700 underline">
        {t('common.back')}
      </Link>
      {conversation && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-medium">{who(conversation)}</p>
            <p className="text-sm text-slate-500">
              {human ? t('inbox.humanHelp') : t('inbox.aiHelp')}
            </p>
          </div>
          {human ? (
            <button
              type="button"
              onClick={() => actions.returnToAi.mutate()}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {t('inbox.returnToAi')}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => actions.takeOver.mutate()}
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm text-white"
            >
              {t('inbox.takeOver')}
            </button>
          )}
        </div>
      )}
      <ul className="space-y-2 rounded-xl bg-white p-3 shadow-sm">
        {messages.data?.map((message) => (
          <Bubble key={message.id} message={message} />
        ))}
      </ul>
      {conversation && !conversation.can_reply ? (
        <p role="note" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          {t('inbox.windowClosed')}
        </p>
      ) : (
        <form onSubmit={send} className="flex gap-2">
          <input
            aria-label={t('inbox.reply')}
            value={text}
            maxLength={2000}
            onChange={(e) => setText(e.target.value)}
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-base"
          />
          <button
            type="submit"
            disabled={actions.reply.isPending || !text.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60"
          >
            {t('inbox.send')}
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error.message}
        </p>
      )}
    </div>
  )
}
