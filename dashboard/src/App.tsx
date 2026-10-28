import { WhatsAppPage } from "./pages/WhatsApp";
import { wa } from "./i18n/whatsapp";
import { LeadsPage } from "./pages/Leads";
import { Notifications } from "./components/Notifications";
import { lt } from "./i18n/leads";
import { QuotesPage } from "./pages/Quotes";
import { qt } from "./i18n/quotes";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { api, hasSession, setTokens, setSessionLost } from "./api/client";
import { Button } from "./components/ui/button";
import { en } from "./i18n/en";
import { knowledge as kt } from "./i18n/knowledge";
import { KnowledgePage } from "./pages/Knowledge";
import { PlaygroundPage } from "./pages/Playground";
import { InboxPage } from "./pages/Inbox";

function AuthPage({ register = false }: { register?: boolean }) {
  const navigate = useNavigate();
  const mutation = useMutation({
    mutationFn: async (form: FormData) => {
      const email = String(form.get("email"));
      const password = String(form.get("password"));
      const result = register
        ? await api.register({
            email,
            password,
            name: String(form.get("name")),
            business_name: String(form.get("business_name")),
            business_type: String(form.get("business_type")),
          })
        : await api.login(email, password);
      setTokens(result);
    },
    onSuccess: () => navigate("/", { replace: true }),
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(new FormData(event.currentTarget));
  }
  return (
    <main className="auth">
      <section className="card">
        <p className="brand">{en.brand}</p>
        <p>{en.tagline}</p>
        <h1>{register ? en.register : en.login}</h1>
        <form onSubmit={submit}>
          {register && (
            <>
              <label>
                {en.business}
                <input name="business_name" required maxLength={200} />
              </label>
              <label>
                {en.businessType}
                <input name="business_type" required maxLength={100} />
              </label>
              <label>
                {en.name}
                <input
                  name="name"
                  autoComplete="name"
                  required
                  maxLength={200}
                />
              </label>
            </>
          )}
          <label>
            {en.email}
            <input name="email" type="email" autoComplete="email" required />
          </label>
          <label>
            {en.password}
            <input
              name="password"
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              required
              minLength={register ? 12 : 1}
              maxLength={128}
            />
          </label>
          {register && <small>{en.passwordHint}</small>}
          {mutation.isError && (
            <p role="alert">{register ? en.registerError : en.error}</p>
          )}
          <Button disabled={mutation.isPending}>
            {mutation.isPending
              ? en.pending
              : register
                ? en.register
                : en.login}
          </Button>
        </form>
        <Link to={register ? "/login" : "/register"}>
          {register ? en.switchLogin : en.switchRegister}
        </Link>
      </section>
    </main>
  );
}
function ProtectedLayout() {
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [active, setActive] = useState(hasSession());
  setSessionLost(() => {
    cache.clear();
    setActive(false);
  });
  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      cache.clear();
      setActive(false);
      navigate("/login");
    },
  });
  if (!active) return <Navigate to="/login" replace />;
  return (
    <div className="workspace">
      <header>
        <Link className="brand" to="/">
          {en.brand}
        </Link>
        <Button
          variant="outline"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          {en.logout}
        </Button>
      </header>
      <nav>
        <Link to="/">{en.home}</Link>
        <Link to="/knowledge">{kt.title}</Link>
        <Link to="/playground">{kt.playground}</Link>
        <Link to="/inbox">{kt.inbox}</Link>
        <Link to="/leads">{lt.title}</Link>
        <Link to="/whatsapp">{wa.title}</Link>
        <Link to="/quotes">{qt.title}</Link>
      </nav>
      <Notifications />
      <main>
        <Outlet />
      </main>
    </div>
  );
}
function Overview() {
  const profile = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  if (profile.isPending) return <p>{en.loading}</p>;
  if (profile.isError) return <p role="alert">{en.error}</p>;
  return (
    <section className="card">
      <p className="eyebrow">{profile.data.name}</p>
      <h1>{en.welcome}</h1>
      <p>{en.foundation}</p>
    </section>
  );
}
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage />} />
      <Route path="/register" element={<AuthPage register />} />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<Overview />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/playground" element={<PlaygroundPage />} />
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/leads" element={<LeadsPage />} />
        <Route path="/whatsapp" element={<WhatsAppPage />} />
        <Route path="/quotes" element={<QuotesPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
