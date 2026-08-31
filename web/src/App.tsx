import { FormEvent, useEffect, useMemo, useState } from "react";
import { createClient, Session, SupabaseClient } from "@supabase/supabase-js";

type Store = {
  id: number;
  nome: string;
  slug?: string;
  numero_loja?: string;
  descricao?: string;
  cidade?: string;
  uf?: string;
  endereco?: string;
  rito?: string;
  potencia?: string;
  potencia_complemento?: string;
  instagram_handle?: string;
  status?: string;
};

type StoreDraft = Omit<Store, "id">;

type Publication = {
  id: number;
  evento_id: number;
  estado: string;
  canal: string;
  artefato_path?: string;
};

type PreparedPublication = {
  publication: Publication;
  artifactUrl: string;
  eventId: number;
  eventTitle: string;
  publicUrl?: string;
};

type EventDraft = {
  titulo: string;
  evento_at: string;
  descricao: string;
  grau: string;
  tipo_sessao: string;
  rito: string;
  traje_obrigatorio: string;
  agape: string;
  ordem_do_dia: string;
  endereco_sessao: string;
};

type PublicEvent = {
  id: number;
  loja_id: number;
  evento_at: string;
  titulo: string;
  descricao?: string;
  grau?: string;
  tipo_sessao?: string;
  rito?: string;
  traje_obrigatorio?: string;
  agape?: string;
  ordem_do_dia?: string;
  endereco_sessao?: string;
  status: string;
  visibilidade?: string;
  public_url?: string;
  loja?: Pick<Store, "id" | "nome" | "numero_loja" | "cidade" | "uf" | "rito" | "instagram_handle">;
};

type Presence = {
  id: number;
  visitante_nome: string;
  visitante_email?: string;
  visitante_telefone?: string;
  agape: string;
  status: string;
};

type Me = {
  profile: { id: string; auth_user_id: string; email: string };
  is_global_admin: boolean;
  store_roles: Record<string, string[]>;
  stores: Store[];
};

type RuntimeConfig = {
  supabase_url: string;
  supabase_publishable_key: string;
  public_base_url?: string;
};

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

function storeDraft(store?: Store): StoreDraft {
  return {
    nome: store?.nome || "",
    slug: store?.slug || "",
    numero_loja: store?.numero_loja || "",
    descricao: store?.descricao || "",
    cidade: store?.cidade || "",
    uf: store?.uf || "",
    endereco: store?.endereco || "",
    rito: store?.rito || "",
    potencia: store?.potencia || "",
    potencia_complemento: store?.potencia_complemento || "",
    instagram_handle: store?.instagram_handle || "",
    status: store?.status || "active",
  };
}

function localDateTimeValue(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function eventDraft(event: PublicEvent): EventDraft {
  return {
    titulo: event.titulo || "",
    evento_at: localDateTimeValue(event.evento_at),
    descricao: event.descricao || "",
    grau: event.grau || "",
    tipo_sessao: event.tipo_sessao || "",
    rito: event.rito || "",
    traje_obrigatorio: event.traje_obrigatorio || "",
    agape: event.agape || "",
    ordem_do_dia: event.ordem_do_dia || "",
    endereco_sessao: event.endereco_sessao || "",
  };
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
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(null);
  const [configError, setConfigError] = useState("");
  const [configLoading, setConfigLoading] = useState(route.kind !== "public");
  const [session, setSession] = useState<Session | null>(null);
  const supabase = useMemo<SupabaseClient | null>(() => {
    if (!runtimeConfig?.supabase_url || !runtimeConfig.supabase_publishable_key) return null;
    return createClient(runtimeConfig.supabase_url, runtimeConfig.supabase_publishable_key);
  }, [runtimeConfig]);

  useEffect(() => {
    if (route.kind === "public") return;
    apiFetch("/api/v1/config")
      .then((data) => setRuntimeConfig(data as RuntimeConfig))
      .catch((reason: Error) => setConfigError(reason.message))
      .finally(() => setConfigLoading(false));
  }, [route.kind]);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => setSession(nextSession));
    return () => data.subscription.unsubscribe();
  }, [supabase]);

  if (route.kind === "public") return <PublicEventPage token={route.token || ""} />;
  if (configLoading) return <Shell><p className="muted">Carregando a configuração segura…</p></Shell>;
  if (configError) return <Shell><Notice tone="warning" title="PWA indisponível">{configError}</Notice></Shell>;
  if (!supabase) return <Shell><Notice tone="warning" title="Configuração pendente">A chave publicável do Supabase ainda não foi configurada neste ambiente.</Notice></Shell>;
  if (!session) return <LoginPage inviteToken={route.kind === "invite" ? route.token : undefined} supabaseClient={supabase} />;
  return <Dashboard session={session} inviteToken={route.kind === "invite" ? route.token : undefined} supabaseClient={supabase} />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="shell"><header className="brand"><div className="brand-mark">BA</div><div><p className="eyebrow">Centro operacional</p><h1>Bode Andarilho</h1></div></header>{children}<footer>Construído em coexistência gradual com o Telegram.</footer></main>;
}

function Notice({ title, children, tone = "info" }: { title: string; children: React.ReactNode; tone?: "info" | "warning" | "success" }) {
  return <div className={`notice notice-${tone}`}><strong>{title}</strong><span>{children}</span></div>;
}

function LoginPage({ inviteToken, supabaseClient }: { inviteToken?: string; supabaseClient: SupabaseClient }) {
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
    const result = await supabaseClient.auth.signInWithOtp({ email: email.trim().toLowerCase(), options: { emailRedirectTo: redirect.toString() } });
    setBusy(false);
    if (result.error) setError(result.error.message);
    else setSent(true);
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    const result = await supabaseClient.auth.verifyOtp({ email: email.trim().toLowerCase(), token: code.trim(), type: "email" });
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

function Dashboard({ session, inviteToken, supabaseClient }: { session: Session; inviteToken?: string; supabaseClient: SupabaseClient }) {
  const [me, setMe] = useState<Me | null>(null);
  const [events, setEvents] = useState<PublicEvent[]>([]);
  const [editingEvent, setEditingEvent] = useState<PublicEvent | null>(null);
  const [editForm, setEditForm] = useState<EventDraft | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [presences, setPresences] = useState<Presence[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [artifactUrl, setArtifactUrl] = useState("");
  const [preparedPublication, setPreparedPublication] = useState<PreparedPublication | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyAction, setBusyAction] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        if (inviteToken) {
          try {
            await apiFetch("/api/v1/convites/consumir", { method: "POST", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify({ token: inviteToken }) }, session);
            if (!cancelled) setMessage("Convite consumido. Seu vínculo está ativo.");
          } catch (reason) {
            // O link pode ser reaberto depois do consumo; nesse caso o perfil
            // já está criado e o painel deve continuar carregando.
            if (!String((reason as Error).message || "").toLowerCase().includes("já consumido")) throw reason;
          }
        }
        const [meData, eventData] = await Promise.all([apiFetch("/api/v1/me", {}, session), apiFetch("/api/v1/eventos", {}, session)]);
        if (!cancelled) { setMe(meData); setEvents(eventData.items || []); }
      } catch (reason) {
        if (!cancelled) setError((reason as Error).message);
      }
    }

    void load();
    return () => { cancelled = true; };
  }, [inviteToken, session]);

  async function logout() { await supabaseClient.auth.signOut(); }

  async function refreshWorkspace() {
    const [meData, eventData] = await Promise.all([
      apiFetch("/api/v1/me", {}, session),
      apiFetch("/api/v1/eventos", {}, session),
    ]);
    setMe(meData); setEvents(eventData.items || []);
  }

  async function createDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      const localDate = String(form.get("evento_at") || "");
      const parsedDate = new Date(localDate);
      if (Number.isNaN(parsedDate.getTime())) throw new Error("Informe uma data e hora válidas.");
      const created = await apiFetch("/api/v1/eventos", { method: "POST", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify({
        titulo: form.get("titulo"), evento_at: parsedDate.toISOString(), loja_id: Number(form.get("loja_id")),
        grau: form.get("grau"), tipo_sessao: form.get("tipo_sessao"), rito: form.get("rito"),
        traje_obrigatorio: form.get("traje_obrigatorio"), agape: form.get("agape"), ordem_do_dia: form.get("ordem_do_dia"),
        status: form.get("publicar") === "on" ? "published" : "draft", visibilidade: form.get("publicar") === "on" ? "public" : "private",
      }) }, session);
      setEvents((current) => [created, ...current]); setMessage(created.status === "published" ? "Evento publicado e link público criado." : "Rascunho de evento criado."); setArtifactUrl(""); event.currentTarget.reset();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  async function updateEvent(eventId: number, status: "published" | "cancelled") {
    setBusyAction(`event-${eventId}-${status}`); setError("");
    try {
      const updated = await apiFetch(`/api/v1/eventos/${eventId}`, { method: "PATCH", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify({ status, ...(status === "published" ? { visibilidade: "public" } : {}) }) }, session);
      setEvents((current) => current.map((item) => item.id === eventId ? { ...item, ...updated } : item));
      setMessage(status === "published" ? "Evento publicado." : "Evento cancelado.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusyAction(""); }
  }

  function beginEventEdit(event: PublicEvent) {
    setEditingEvent(event); setEditForm(eventDraft(event)); setError("");
  }

  function updateEventDraft(field: keyof EventDraft, value: string) {
    setEditForm((current) => current ? { ...current, [field]: value } : current);
  }

  async function saveEventEdit(event: FormEvent) {
    event.preventDefault();
    if (!editingEvent || !editForm) return;
    const parsedDate = new Date(editForm.evento_at);
    if (Number.isNaN(parsedDate.getTime())) { setError("Informe uma data e hora válidas."); return; }
    setBusyAction(`edit-event-${editingEvent.id}`); setError("");
    try {
      const updated = await apiFetch(`/api/v1/eventos/${editingEvent.id}`, {
        method: "PATCH",
        headers: { "Idempotency-Key": newKey() },
        body: JSON.stringify({ ...editForm, evento_at: parsedDate.toISOString() }),
      }, session);
      setEvents((current) => current.map((item) => item.id === editingEvent.id ? { ...item, ...updated } : item));
      setEditingEvent((current) => current ? { ...current, ...updated } : current);
      setEditForm(eventDraft({ ...editingEvent, ...updated }));
      setMessage("Evento atualizado.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusyAction(""); }
  }

  async function generateCard(eventId: number, channel: "instagram" | "whatsapp" = "instagram") {
    setBusyAction(`card-${eventId}-${channel}`); setError(""); setArtifactUrl("");
    try {
      const data = await apiFetch(`/api/v1/eventos/${eventId}/card`, { method: "POST", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify({ canal: channel }) }, session);
      const event = events.find((item) => item.id === eventId);
      setPreparedPublication({
        publication: data.publication,
        artifactUrl: data.artifact?.url || "",
        eventId,
        eventTitle: event?.titulo || "Sessão",
        publicUrl: event?.public_url,
      });
      setMessage("Card preparado. A publicação externa ainda precisa ser confirmada pelo usuário.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusyAction(""); }
  }

  async function setPublicationState(publicationId: number, state: "share_initiated" | "confirmed_by_user" | "failed", erro?: string) {
    const data = await apiFetch(`/api/v1/publicacoes/${publicationId}/estado`, {
      method: "POST",
      headers: { "Idempotency-Key": newKey() },
      body: JSON.stringify({ estado: state, ...(erro ? { erro } : {}) }),
    }, session);
    setPreparedPublication((current) => current && current.publication.id === publicationId ? {
      ...current,
      publication: { ...current.publication, ...data },
    } : current);
    return data;
  }

  async function sharePreparedPublication() {
    const prepared = preparedPublication;
    if (!prepared || prepared.publication.estado === "confirmed_by_user") return;
    setBusyAction(`share-${prepared.publication.id}`); setError("");
    const targetUrl = prepared.publicUrl || prepared.artifactUrl;
    try {
      if (prepared.publication.estado === "prepared") {
        await setPublicationState(prepared.publication.id, "share_initiated");
      }
      if (typeof navigator.share === "function") {
        await navigator.share({ title: prepared.eventTitle, text: prepared.eventTitle, url: targetUrl });
        setMessage("O compartilhamento foi aberto. Confirme abaixo somente depois de concluir a ação no canal externo.");
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(targetUrl);
        setMessage("Link copiado. Abra o Instagram ou WhatsApp, conclua a ação e confirme abaixo.");
      } else {
        setMessage("Abra o card e use o menu do dispositivo para compartilhar; confirme abaixo ao concluir.");
      }
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setMessage("Compartilhamento cancelado. A publicação externa não foi considerada comprovada.");
      } else {
        const messageText = (reason as Error).message || "falha ao abrir o compartilhamento";
        try { await setPublicationState(prepared.publication.id, "failed", messageText.slice(0, 1000)); } catch { /* o erro original é o relevante para o operador */ }
        setError(messageText);
      }
    } finally { setBusyAction(""); }
  }

  async function confirmPreparedPublication() {
    const prepared = preparedPublication;
    if (!prepared || prepared.publication.estado !== "share_initiated") return;
    setBusyAction(`confirm-share-${prepared.publication.id}`); setError("");
    try {
      await setPublicationState(prepared.publication.id, "confirmed_by_user");
      setMessage("A ação foi registrada como confirmada pelo usuário; isso não é evidência de publicação via API.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusyAction(""); }
  }

  async function loadPresences(eventId: number) {
    setSelectedEventId(eventId); setBusyAction(`presence-${eventId}`); setError("");
    try { const data = await apiFetch(`/api/v1/eventos/${eventId}/presencas`, {}, session); setPresences(data.items || []); }
    catch (reason) { setError((reason as Error).message); } finally { setBusyAction(""); }
  }

  async function reviewPresence(presenceId: number, status: "aprovar" | "recusar") {
    setBusyAction(`review-${presenceId}`); setError("");
    try {
      const data = await apiFetch(`/api/v1/presencas/${presenceId}/${status}`, { method: "POST", headers: { "Idempotency-Key": newKey() }, body: "{}" }, session);
      setPresences((current) => current.map((item) => item.id === presenceId ? { ...item, ...data } : item)); setMessage("Solicitação atualizada.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusyAction(""); }
  }

  async function createInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusyAction("invite"); setError("");
    try {
      const form = new FormData(event.currentTarget); const storeValue = String(form.get("loja_id") || "");
      const body: Record<string, unknown> = { email: form.get("email"), papel: form.get("papel") };
      if (storeValue) body.loja_id = Number(storeValue);
      const data = await apiFetch("/api/v1/convites", { method: "POST", headers: { "Idempotency-Key": newKey() }, body: JSON.stringify(body) }, session);
      setMessage("Convite criado. Copie o link antes de fechar esta tela."); setArtifactUrl(data.invite_url || ""); event.currentTarget.reset();
    } catch (reason) { setError((reason as Error).message); } finally { setBusyAction(""); }
  }

  return <Shell>
    <section className="dashboard-head"><div><p className="eyebrow">Painel autenticado</p><h2>{me?.profile.email || "Sua operação"}</h2><p className="muted">Acesso filtrado pelos vínculos reais de loja.</p></div><button className="button-quiet" onClick={logout}>Sair</button></section>
    {message && <Notice tone="success" title="Tudo certo">{message}</Notice>}
    {error && <Notice tone="warning" title="Atenção">{error}</Notice>}
    {me && <section className="grid two"><div className="panel"><p className="eyebrow">Lojas autorizadas</p><h3>{me.stores.length}</h3><div className="chips">{me.stores.map((store) => <span className="chip" key={store.id}>{store.nome}</span>)}</div></div><div className="panel"><p className="eyebrow">Eventos visíveis</p><h3>{events.length}</h3><p className="muted">Telegram continua disponível durante o piloto.</p></div></section>}
    {me && <section className="panel"><div className="section-title"><div><p className="eyebrow">Núcleo operacional</p><h3>Criar sessão</h3></div><span className="status">rascunho</span></div><form onSubmit={createDraft} className="form-grid"><label>Título<input name="titulo" required placeholder="Sessão de trabalho" /></label><label>Data e hora<input name="evento_at" required type="datetime-local" /></label><label>Loja<select name="loja_id" required defaultValue=""> <option value="" disabled>Selecione</option>{me.stores.map((store) => <option key={store.id} value={store.id}>{store.nome}</option>)}</select></label><label>Grau<select name="grau" defaultValue=""><option value="">Não informado</option><option>Aprendiz</option><option>Companheiro</option><option>Mestre</option></select></label><label>Tipo de sessão<input name="tipo_sessao" placeholder="Ordinária, magna…" /></label><label>Rito<input name="rito" placeholder="REAA" /></label><label>Traje<input name="traje_obrigatorio" placeholder="Livre ou traje maçônico" /></label><label>Ágape<input name="agape" placeholder="Sem ágape" /></label><label className="wide">Ordem do dia<textarea name="ordem_do_dia" rows={2} placeholder="Pauta ou observações (opcional)" /></label><label className="check wide"><input name="publicar" type="checkbox" /> Publicar agora e gerar link público</label><button disabled={busy}>{busy ? "Salvando…" : "Salvar sessão"}</button></form></section>}
    {me && (me.is_global_admin || Object.values(me.store_roles).some((roles) => roles.includes("admin"))) && <StoreAdminPanel me={me} session={session} onSaved={refreshWorkspace} />}
    {me && <TelegramAssociationPanel session={session} />}
    {me?.is_global_admin && <section className="panel"><div className="section-title"><div><p className="eyebrow">Acesso controlado</p><h3>Enviar convite</h3></div></div><form onSubmit={createInvite} className="form-grid"><label>E-mail<input name="email" required type="email" placeholder="secretario@exemplo.com" /></label><label>Papel<select name="papel" defaultValue="secretary"><option value="secretary">Secretário</option><option value="member">Membro</option><option value="admin">Administrador</option></select></label><label>Loja<select name="loja_id" defaultValue=""><option value="">Administrador global</option>{me.stores.map((store) => <option key={store.id} value={store.id}>{store.nome}</option>)}</select></label><button disabled={busyAction === "invite"}>{busyAction === "invite" ? "Criando…" : "Criar convite"}</button></form></section>}
    {message && artifactUrl && <Notice tone="success" title="Resultado"><a href={artifactUrl} target="_blank" rel="noreferrer">Abrir resultado seguro</a></Notice>}
    {preparedPublication && <section className="panel"><div className="section-title"><div><p className="eyebrow">Compartilhamento assistido</p><h3>{preparedPublication.eventTitle}</h3></div><span className="status">{preparedPublication.publication.estado}</span></div><p className="muted">Canal: {preparedPublication.publication.canal}. A abertura da folha de compartilhamento não comprova publicação externa.</p><div className="event-actions"><a className="button-small button-quiet" href={preparedPublication.artifactUrl} target="_blank" rel="noreferrer">Abrir card</a>{preparedPublication.publicUrl && <a className="button-small button-quiet" href={preparedPublication.publicUrl} target="_blank" rel="noreferrer">Abrir link público</a>}{preparedPublication.publication.estado !== "confirmed_by_user" && preparedPublication.publication.estado !== "failed" && <button className="button-small" disabled={busyAction === `share-${preparedPublication.publication.id}`} onClick={sharePreparedPublication}>Compartilhar</button>}{preparedPublication.publication.estado === "share_initiated" && <button className="button-small" disabled={busyAction === `confirm-share-${preparedPublication.publication.id}`} onClick={confirmPreparedPublication}>Confirmar ação concluída</button>}</div></section>}
    <section className="panel"><div className="section-title"><div><p className="eyebrow">Agenda</p><h3>Eventos</h3></div></div>{events.length === 0 ? <p className="muted">Nenhum evento disponível ainda.</p> : <div className="event-list">{events.map((event) => <article className="event-row" key={event.id}><div className="event-main"><strong>{event.titulo}</strong><span>{formatDate(event.evento_at)}</span>{event.public_url && <a href={event.public_url} target="_blank" rel="noreferrer">Abrir link público</a>}</div><div className="event-actions"><span className="status">{event.status}</span>{event.status !== "cancelled" && event.status !== "closed" && <button className="button-small button-quiet" disabled={busyAction === `edit-event-${event.id}`} onClick={() => beginEventEdit(event)}>Editar</button>}{event.status === "draft" && <button className="button-small" disabled={busyAction === `event-${event.id}-published`} onClick={() => updateEvent(event.id, "published")}>Publicar</button>}{event.status !== "cancelled" && event.status !== "closed" && <button className="button-small button-quiet" disabled={busyAction === `event-${event.id}-cancelled`} onClick={() => updateEvent(event.id, "cancelled")}>Cancelar</button>}<button className="button-small button-quiet" disabled={busyAction === `card-${event.id}-instagram`} onClick={() => generateCard(event.id, "instagram")}>Card Instagram</button><button className="button-small button-quiet" disabled={busyAction === `card-${event.id}-whatsapp`} onClick={() => generateCard(event.id, "whatsapp")}>Card WhatsApp</button><button className="button-small button-quiet" disabled={busyAction === `presence-${event.id}`} onClick={() => loadPresences(event.id)}>Presenças</button></div></article>)}</div>}</section>
    {editingEvent && editForm && <section className="panel"><div className="section-title"><div><p className="eyebrow">Edição operacional</p><h3>{editingEvent.titulo}</h3></div><button className="button-small button-quiet" onClick={() => { setEditingEvent(null); setEditForm(null); }}>Fechar</button></div><form onSubmit={saveEventEdit} className="form-grid"><label>Título<input required value={editForm.titulo} onChange={(event) => updateEventDraft("titulo", event.target.value)} /></label><label>Data e hora<input required type="datetime-local" value={editForm.evento_at} onChange={(event) => updateEventDraft("evento_at", event.target.value)} /></label><label>Grau<select value={editForm.grau} onChange={(event) => updateEventDraft("grau", event.target.value)}><option value="">Não informado</option><option>Aprendiz</option><option>Companheiro</option><option>Mestre</option></select></label><label>Tipo de sessão<input value={editForm.tipo_sessao} onChange={(event) => updateEventDraft("tipo_sessao", event.target.value)} /></label><label>Rito<input value={editForm.rito} onChange={(event) => updateEventDraft("rito", event.target.value)} /></label><label>Traje<input value={editForm.traje_obrigatorio} onChange={(event) => updateEventDraft("traje_obrigatorio", event.target.value)} /></label><label>Ágape<input value={editForm.agape} onChange={(event) => updateEventDraft("agape", event.target.value)} /></label><label className="wide">Descrição<textarea rows={2} value={editForm.descricao} onChange={(event) => updateEventDraft("descricao", event.target.value)} /></label><label className="wide">Ordem do dia<textarea rows={3} value={editForm.ordem_do_dia} onChange={(event) => updateEventDraft("ordem_do_dia", event.target.value)} /></label><label className="wide">Endereço da sessão<textarea rows={2} value={editForm.endereco_sessao} onChange={(event) => updateEventDraft("endereco_sessao", event.target.value)} /></label><button disabled={busyAction === `edit-event-${editingEvent.id}`}>{busyAction === `edit-event-${editingEvent.id}` ? "Salvando…" : "Salvar alterações"}</button></form></section>}
    {selectedEventId !== null && <section className="panel"><div className="section-title"><div><p className="eyebrow">Revisão</p><h3>Solicitações de presença</h3></div><span className="status">{presences.length}</span></div>{presences.length === 0 ? <p className="muted">Nenhuma solicitação para este evento.</p> : <div className="event-list">{presences.map((presence) => <article className="event-row" key={presence.id}><div className="event-main"><strong>{presence.visitante_nome}</strong><span>{presence.visitante_email || presence.visitante_telefone || "Contato não informado"} · Ágape: {presence.agape}</span></div><div className="event-actions"><span className="status">{presence.status}</span>{presence.status === "pending" && <><button className="button-small" disabled={busyAction === `review-${presence.id}`} onClick={() => reviewPresence(presence.id, "aprovar")}>Aprovar</button><button className="button-small button-quiet" disabled={busyAction === `review-${presence.id}`} onClick={() => reviewPresence(presence.id, "recusar")}>Recusar</button></>}</div></article>)}</div>}</section>}
  </Shell>;
}

function StoreAdminPanel({ me, session, onSaved }: { me: Me; session: Session; onSaved: () => Promise<void> }) {
  const manageableStores = me.stores.filter((store) => me.is_global_admin || (me.store_roles[String(store.id)] || []).includes("admin"));
  const canCreate = me.is_global_admin;
  const [selected, setSelected] = useState(canCreate ? "new" : String(manageableStores[0]?.id || ""));
  const [form, setForm] = useState<StoreDraft>(() => storeDraft());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (selected === "new") {
      if (canCreate) setForm(storeDraft());
      return;
    }
    const current = manageableStores.find((store) => String(store.id) === selected);
    if (current) setForm(storeDraft(current));
  }, [selected, me.stores, me.is_global_admin]);

  function updateField(field: keyof StoreDraft, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const path = selected === "new" ? "/api/v1/lojas" : `/api/v1/lojas/${selected}`;
      const data = await apiFetch(path, {
        method: selected === "new" ? "POST" : "PATCH",
        headers: { "Idempotency-Key": newKey() },
        body: JSON.stringify(form),
      }, session);
      if (selected === "new" && data.id) setSelected(String(data.id));
      await onSaved();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  if (!canCreate && manageableStores.length === 0) return null;
  return <section className="panel"><div className="section-title"><div><p className="eyebrow">Cadastro institucional</p><h3>Dados da loja</h3></div><span className="status">{selected === "new" ? "nova" : "edição"}</span></div><form onSubmit={save} className="form-grid"><label>Loja<select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={!canCreate && manageableStores.length < 2}>{canCreate && <option value="new">Nova loja</option>}{manageableStores.map((store) => <option key={store.id} value={store.id}>{store.nome}</option>)}</select></label><label>Nome<input required value={form.nome} onChange={(event) => updateField("nome", event.target.value)} placeholder="Loja Bode Andarilho" /></label><label>Slug<input value={form.slug} onChange={(event) => updateField("slug", event.target.value)} placeholder="loja-exemplo" /></label><label>Número<input value={form.numero_loja} onChange={(event) => updateField("numero_loja", event.target.value)} /></label><label>Cidade<input value={form.cidade} onChange={(event) => updateField("cidade", event.target.value)} /></label><label>UF<input value={form.uf} onChange={(event) => updateField("uf", event.target.value)} maxLength={3} /></label><label>Rito<input value={form.rito} onChange={(event) => updateField("rito", event.target.value)} /></label><label>Potência<input value={form.potencia} onChange={(event) => updateField("potencia", event.target.value)} /></label><label>Instagram<input value={form.instagram_handle} onChange={(event) => updateField("instagram_handle", event.target.value)} placeholder="bodeandarilho" /></label><label className="wide">Descrição<textarea rows={2} value={form.descricao} onChange={(event) => updateField("descricao", event.target.value)} /></label><label className="wide">Endereço<textarea rows={2} value={form.endereco} onChange={(event) => updateField("endereco", event.target.value)} /></label><button disabled={busy}>{busy ? "Salvando…" : selected === "new" ? "Cadastrar loja" : "Salvar dados da loja"}</button></form>{error && <Notice tone="warning" title="Não foi possível salvar">{error}</Notice>}</section>;
}

function TelegramAssociationPanel({ session }: { session: Session }) {
  const [code, setCode] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function generateCode() {
    setBusy(true); setError(""); setCode("");
    try {
      const data = await apiFetch("/api/v1/identidades/telegram/codigo", { method: "POST", headers: { "Idempotency-Key": newKey() }, body: "{}" }, session);
      setCode(data.codigo || ""); setValidUntil(data.valid_until || "");
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  return <section className="panel"><div className="section-title"><div><p className="eyebrow">Coexistência de canais</p><h3>Associar Telegram</h3></div><span className="status">opcional</span></div><p className="muted">Gere um código temporário e use <strong>/vincular código</strong> no chat privado do bot. A associação não migra registros antigos nem ativa mutações do Telegram na PWA.</p>{code && <Notice tone="success" title="Código de uso único"><code>{code}</code><span>Válido até {new Date(validUntil).toLocaleString("pt-BR")}.</span></Notice>}<button onClick={generateCode} disabled={busy}>{busy ? "Gerando…" : code ? "Gerar novo código" : "Gerar código"}</button>{error && <Notice tone="warning" title="Não foi possível gerar">{error}</Notice>}</section>;
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
  return <Shell><section className="panel public-card"><p className="eyebrow">Convite público</p><h2>{event?.titulo || "Carregando evento…"}</h2>{event && <><p className="date-line">{event.loja?.nome || `Loja ${event.loja_id}`}</p><p className="date-line">{formatDate(event.evento_at)}</p>{event.descricao && <p className="muted">{event.descricao}</p>}{event.rito && <p className="muted">Rito: {event.rito}</p>}{event.traje_obrigatorio && <p className="muted">Traje: {event.traje_obrigatorio}</p>}{receipt ? <Notice tone="success" title="Solicitação recebida">Guarde este recibo: <code>{receipt}</code>. A confirmação ficará pendente de revisão.</Notice> : <form onSubmit={submit} className="stack"><label>Seu nome<input required value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></label><label>E-mail (opcional)<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><label>Telefone (opcional)<input value={form.telefone} onChange={(e) => setForm({ ...form, telefone: e.target.value })} /></label><label>Ágape<select value={form.agape} onChange={(e) => setForm({ ...form, agape: e.target.value })}><option value="sem">Sem ágape</option><option value="com">Com ágape</option><option value="gratuito">Ágape gratuito</option><option value="pago">Ágape pago</option></select></label><button disabled={busy}>{busy ? "Enviando…" : "Solicitar presença"}</button></form>}</>}</section>{error && <Notice tone="warning" title="Não foi possível enviar">{error}</Notice>}</Shell>;
}
