import { useState, type FormEvent } from 'react'

import { useAgentRuns, useConversationMessages, useSendPlayground } from '../api/chat'
import { t } from '../i18n/en'

export function PlaygroundPage() {
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const send = useSendPlayground()
  const messages = useConversationMessages(conversationId)
  const list = messages.data ?? []

  const waiting = list.at(-1)?.direction === 'in' // the assistant has not answered yet

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!text.trim()) return
    send.mutate(
      { conversationId, text },
      {
        onSuccess: (sent) => {
          setConversationId(sent.conversation_id)
          setText('')
        },
      },
    )
  }

  return (
    <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">{t('playground.title')}</h1>
          <button
            type="button"
            onClick={() => {
              setConversationId(null)
              setSelected(null)
            }}
            className="text-sm text-indigo-700 underline"
          >
            {t('playground.new')}
          </button>
        </div>
        <p className="text-sm text-slate-500">{t('playground.help')}</p>
        <ul className="min-h-40 space-y-2 rounded-xl bg-white p-3 shadow-sm" aria-live="polite">
          {list.map((message) =>
            message.direction === 'in' ? (
              <li
                key={message.id}
                className="ml-auto w-fit max-w-[85%] rounded-2xl bg-indigo-600 px-3 py-2 text-white"
              >
                {message.content}
              </li>
            ) : (
              <li key={message.id}>
                <button
                  type="button"
                  onClick={() => setSelected(message.reply_to_id)}
                  className={`w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-left ${
                    selected && selected === message.reply_to_id
                      ? 'bg-indigo-50 ring-2 ring-indigo-300'
                      : 'bg-slate-100'
                  }`}
                >
                  {message.content}
                </button>
              </li>
            ),
          )}
          {waiting && <li className="text-sm text-slate-500">{t('playground.thinking')}</li>}
        </ul>
        <form onSubmit={onSubmit} className="flex gap-2">
          <input
            aria-label={t('playground.placeholder')}
            placeholder={t('playground.placeholder')}
            maxLength={2000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-base"
          />
          <button
            type="submit"
            disabled={send.isPending}
            className="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60"
          >
            {t('playground.send')}
          </button>
        </form>
        {send.error && (
          <p role="alert" className="text-sm text-red-600">
            {send.error.message}
          </p>
        )}
      </section>
      <TracePanel messageId={selected} />
    </div>
  )
}

function TracePanel({ messageId }: { messageId: string | null }) {
  const runs = useAgentRuns(messageId)
  return (
    <aside className="space-y-2 rounded-xl bg-white p-3 shadow-sm">
      <h2 className="font-semibold">{t('playground.trace')}</h2>
      {messageId === null && <p className="text-sm text-slate-500">{t('playground.pick')}</p>}
      <ol className="space-y-2">
        {runs.data?.map((run) => (
          <li key={run.id} className="rounded-lg border border-slate-200 p-2 text-sm">
            <p className="font-medium">
              {run.agent}{' '}
              <span className={run.status === 'ok' ? 'text-green-700' : 'text-red-600'}>
                {run.status}
              </span>
            </p>
            <p className="text-xs text-slate-500">
              {run.model ?? '–'} · {run.latency_ms} ms · {run.prompt_tokens + run.completion_tokens}{' '}
              tokens
            </p>
            <p className="text-xs text-slate-500">{run.prompt_version}</p>
            {run.tool_calls.length > 0 && (
              <p className="text-xs">tools: {run.tool_calls.map((c) => c.tool).join(', ')}</p>
            )}
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-slate-50 p-1 text-xs">
              {JSON.stringify(run.output, null, 2)}
            </pre>
          </li>
        ))}
      </ol>
    </aside>
  )
}
