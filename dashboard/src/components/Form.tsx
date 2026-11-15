import type { InputHTMLAttributes, ReactNode } from 'react'

export function Field({
  label,
  ...input
}: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <input
        {...input}
        className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-base shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
    </label>
  )
}

export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow">
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {children}
      </div>
    </main>
  )
}

export function SubmitButton({ children, busy }: { children: ReactNode; busy: boolean }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
    >
      {children}
    </button>
  )
}
