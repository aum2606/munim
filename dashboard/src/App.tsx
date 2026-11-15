import { Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { ProtectedRoute } from './components/ProtectedRoute'
import { HomePage } from './pages/HomePage'
import { InboxPage } from './pages/InboxPage'
import { KnowledgePage } from './pages/KnowledgePage'
import { LoginPage } from './pages/LoginPage'
import { PlaygroundPage } from './pages/PlaygroundPage'
import { RegisterPage } from './pages/RegisterPage'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/knowledge/*" element={<KnowledgePage />} />
          <Route path="/playground" element={<PlaygroundPage />} />
          <Route path="/inbox/*" element={<InboxPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
