-- Persistencia de notificacoes pendentes do secretario
-- Execute este script no SQL Editor do Supabase.

create table if not exists public.notificacoes_secretario_pendentes (
    id bigserial primary key,
    secretario_id bigint not null,
    nome text not null default '',
    data_sessao text not null default '',
    loja text not null default '',
    agape text not null default '',
    criado_em timestamptz not null default now()
);

create index if not exists idx_notif_secretario_pendentes_secretario_id
    on public.notificacoes_secretario_pendentes (secretario_id);

create index if not exists idx_notif_secretario_pendentes_criado_em
    on public.notificacoes_secretario_pendentes (criado_em);
