import { Link, Route, Routes, useParams } from 'react-router-dom'

import { useConversationMessages, useConversations } from '../api/chat'
import { t } from '../i18n/en'

export function InboxPage() {
  return (
    <Routes>
      <Route index element={<ConversationList />} />
      <Route path=":conversationId" element={<ConversationView />} />
    </Routes>
  )
}

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
              className="flex items-center justify-between rounded-lg bg-white p-3 shadow-sm"
            >
              <span>
                {conversation.channel} ·{' '}
                {new Date(
                  conversation.last_customer_msg_at ?? conversation.created_at,
                ).toLocaleString()}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-xs ${
                  conversation.mode === 'human'
                    ? 'bg-amber-100 text-amber-800'
                    : 'bg-green-100 text-green-800'
                }`}
              >
                {t(conversation.mode === 'human' ? 'inbox.mode.human' : 'inbox.mode.ai')}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ConversationView() {
  const { conversationId = null } = useParams()
  const messages = useConversationMessages(conversationId)
  return (
    <div className="space-y-3">
      <Link to="/inbox" className="text-sm text-indigo-700 underline">
        {t('common.back')}
      </Link>
      <ul className="space-y-2 rounded-xl bg-white p-3 shadow-sm">
        {messages.data?.map((message) => (
          <li
            key={message.id}
            className={`w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 ${
              message.direction === 'in' ? 'ml-auto bg-indigo-600 text-white' : 'bg-slate-100'
            }`}
          >
            {message.content}
          </li>
        ))}
      </ul>
    </div>
  )
}
