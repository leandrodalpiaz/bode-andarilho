import { FormEvent, useEffect, useMemo, useState } from "react";
import { createClient, Session, SupabaseClient } from "@supabase/supabase-js";

type PublicEvent = {
  id: number;
  loja_id: number;
  evento_at: string;
  titulo: string;
  descricao?: string;
  status: string;
};

type Me = {
  profile: { id: string; auth_user_id: string; email: string };
  is_global_admin: boolean;
  store_roles: Record<string, string[]>;
  stores: Array<{ id: number; nome: string; cidade?: string; uf?: string }>;
};

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const supabaseKey = (import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY) as string | undefined;
const supabase: SupabaseClient | null = supabaseUrl && supabaseKey ? createClient(supabaseUrl, supabaseKey) : null;

function newKey(): string {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function apiError(data: unknown): string {
  if (typeof data === "object" && data && "error" in data) {
    const error = (data as { error?: { message?: string } }).error;
    if (error?.message) return error.message;
  }
  return "Não foi possível concluir a operação.";
}

async function apiFetch(path: string, init: RequestInit = {}, session?: Session | null): Promise<any> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (session?.access_token) headers.set("Authorization", `Bearer ${session.access_token}`);
  const response = await fetch(path, { ...init, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiError(data));
  return data;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "full", timeStyle: "short" }).format(new Date(value));
}

function routeInfo(): { kind: "public" | "invite" | "dashboard"; token?: string } {
  const path = window.location.pathname;
  const params = new URLSearchParams(window.location.search);
  if (path.startsWith("/evento/")) return { kind: "public", token: decodeURIComponent(path.slice("/evento/".length)) };
  if (path === "/convite") return { kind: "invite", token: params.get("token") || undefined };
  return { kind: "dashboard" };
}

export function App() {
  const route = useMemo(routeInfo, []);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(Boolean(supabase));

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => setSession(nextSession));
    return () => data.subscription.unsubscribe();
  }, []);

  if (route.kind === "public") return <PublicEventPage token={route.token || ""} />;
  if (!supabase) return <Shell><Notice tone="warning" title="Configuração pendente">O frontend está pronto, mas as variáveis públicas do Supabase ainda não foram configuradas neste ambiente.</Notice></Shell>;
  if (loading) return <Shell><p className="muted">Carregando sua sessão…</p></Shell>;
  if (!session) return <LoginPage inviteToken={route.kind === "invite" ? route.token : undefined} />;
  return <Dashboard session={session} inviteToken={route.kind === "invite" ? route.token : undefined} />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="shell"><header className="brand"><div className="brand-mark">BA</div><div><p className="eyebrow">Centro operacional</p><h1>Bode Andarilho</h1></div></header>{children}<footer>Construído em coexistência gradual com o Telegram.</footer></main>;
}

function Notice({ title, children, tone = "info" }: { title: string; children: React.ReactNode; tone?: "info" | "warning" | "success" }) {
  return <div className={`notice notice-${tone}`}><strong>{title}</strong><span>{children}</span></div>;
}

function LoginPage({ inviteToken }: { inviteToken?: string }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    const redirect = new URL(inviteToken ? "/convite" : "/", window.location.origin);
    if (inviteToken) redirect.searchParams.set("token", inviteToken);
    const result = await supabase!.auth.signInWithOtp({ email: email.trim().toLowerCase(), options: { emailRedirectTo: redirect.toString() } });
    setBusy(false);
    if (result.error) setError(result.error.message);
    else setSent(true);
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    const result = await supabase!.auth.verifyOtp({ email: email.trim().toLowerCase(), token: code.trim(), type: "email" });
    setBusy(false);
    if (result.error) setError(result.error.message);
  }

  return <Shell>
    <section className="panel narrow">
      <p className="eyebrow">{inviteToken ? "Convite de acesso" : "Acesso seguro"}</p>
      <h2>{inviteToken ? "Ative sua conta" : "Entrar na PWA"}</h2>
      <p className="muted">Use o e-mail autorizado. O código de acesso é enviado pelo Supabase Auth.</p>
      {sent ? <><Notice tone="success" title="Código enviado">Confira sua caixa de entrada. Você pode clicar no link ou informar o código recebido.</Notice><form onSubmit={verify} className="stack"><label>Código<input required inputMode="numeric" value={code} onChange={(event) => setCode(event.target.value)} placeholder="123456" /></label><button disabled={busy}>{busy ? "Validando…" : "Confirmar código"}</button></form></> : <form onSubmit={submit} className="stack">
        <label>E-mail<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="voce@exemplo.com" autoComplete="email" /></label>
        <button disabled={busy}>{busy ? "Enviando…" : "Enviar código por e-mail"}</button>
      </form>}
      {error && <Notice tone="warning" title="Não foi possível entrar">{error}</Notice>}
    </section>
  </Shell>;
}

function Dashboard({ session, inviteToken }: { session: Session; inviteToken?: string }) {
  const [me, setMe] = useState<Me | null>(null);
  const [events, setEvents] = useState<PublicEvent[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([apiFetch("/api/v1/me", {}, session), apiFetch("/api/v1/eventos", {}, session)])
      .then(([meData, eventData]) => { if (!cancelled) { setMe(meData); setEvents(eventData.items || []); } })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [session]);

  useEffect(() => {
    if (!inviteToken) return;
    apiFetch("/api/v1/convites/consumir", { method: "POST", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify({ token: inviteToken }) }, session)
      .then(() => setMessage("Convite consumido. Seu vínculo está ativo."))
      .catch((reason: Error) => setError(reason.message));
  }, [inviteToken, session]);

  async function logout() { await supabase!.auth.signOut(); }

  async function createDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      const localDate = String(form.get("evento_at") || "");
      const created = await apiFetch("/api/v1/eventos", { method: "POST", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify({ titulo: form.get("titulo"), evento_at: new Date(localDate).toISOString(), loja_id: Number(form.get("loja_id")) }) }, session);
      setEvents((current) => [...current, created]); setMessage("Rascunho de evento criado."); event.currentTarget.reset();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  return <Shell>
    <section className="dashboard-head"><div><p className="eyebrow">Painel autenticado</p><h2>{me?.profile.email || "Sua operação"}</h2><p className="muted">Acesso filtrado pelos vínculos reais de loja.</p></div><button className="button-quiet" onClick={logout}>Sair</button></section>
    {message && <Notice tone="success" title="Tudo certo">{message}</Notice>}
    {error && <Notice tone="warning" title="Atenção">{error}</Notice>}
    {me && <section className="grid two"><div className="panel"><p className="eyebrow">Lojas autorizadas</p><h3>{me.stores.length}</h3><div className="chips">{me.stores.map((store) => <span className="chip" key={store.id}>{store.nome}</span>)}</div></div><div className="panel"><p className="eyebrow">Eventos visíveis</p><h3>{events.length}</h3><p className="muted">Telegram continua disponível durante o piloto.</p></div></section>}
    {me && <section className="panel"><div className="section-title"><div><p className="eyebrow">Próximo núcleo</p><h3>Criar sessão</h3></div><span className="status">rascunho</span></div><form onSubmit={createDraft} className="form-grid"><label>Título<input name="titulo" required placeholder="Sessão de trabalho" /></label><label>Data e hora<input name="evento_at" required type="datetime-local" /></label><label>Loja<select name="loja_id" required defaultValue=""> <option value="" disabled>Selecione</option>{me.stores.map((store) => <option key={store.id} value={store.id}>{store.nome}</option>)}</select></label><button disabled={busy}>{busy ? "Salvando…" : "Salvar rascunho"}</button></form></section>}
    <section className="panel"><div className="section-title"><div><p className="eyebrow">Agenda</p><h3>Eventos</h3></div></div>{events.length === 0 ? <p className="muted">Nenhum evento disponível ainda.</p> : <div className="event-list">{events.map((event) => <article className="event-row" key={event.id}><div><strong>{event.titulo}</strong><span>{formatDate(event.evento_at)}</span></div><span className="status">{event.status}</span></article>)}</div>}</section>
  </Shell>;
}

function PublicEventPage({ token }: { token: string }) {
  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [form, setForm] = useState({ nome: "", email: "", telefone: "", agape: "sem" });
  const [receipt, setReceipt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { apiFetch(`/api/v1/public/eventos/${encodeURIComponent(token)}`).then(setEvent).catch((reason: Error) => setError(reason.message)); }, [token]);

  async function submit(eventSubmit: FormEvent) {
    eventSubmit.preventDefault(); setBusy(true); setError("");
    try {
      const data = await apiFetch(`/api/v1/public/eventos/${encodeURIComponent(token)}/presencas`, { method: "POST", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify(form) });
      setReceipt(data.receipt); setForm({ nome: "", email: "", telefone: "", agape: "sem" });
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  if (error && !event) return <Shell><Notice tone="warning" title="Link indisponível">{error}</Notice></Shell>;
  return <Shell><section className="panel public-card"><p className="eyebrow">Convite público</p><h2>{event?.titulo || "Carregando evento…"}</h2>{event && <><p className="date-line">{formatDate(event.evento_at)}</p>{event.descricao && <p className="muted">{event.descricao}</p>}{receipt ? <Notice tone="success" title="Solicitação recebida">Guarde este recibo: <code>{receipt}</code>. A confirmação ficará pendente de revisão.</Notice> : <form onSubmit={submit} className="stack"><label>Seu nome<input required value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></label><label>E-mail (opcional)<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><label>Telefone (opcional)<input value={form.telefone} onChange={(e) => setForm({ ...form, telefone: e.target.value })} /></label><label>Ágape<select value={form.agape} onChange={(e) => setForm({ ...form, agape: e.target.value })}><option value="sem">Sem ágape</option><option value="com">Com ágape</option><option value="gratuito">Ágape gratuito</option><option value="pago">Ágape pago</option></select></label><button disabled={busy}>{busy ? "Enviando…" : "Solicitar presença"}</button></form>}</>}</section>{error && <Notice tone="warning" title="Não foi possível enviar">{error}</Notice>}</Shell>;
}
