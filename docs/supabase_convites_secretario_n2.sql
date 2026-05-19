-- Convites diretos para cadastro de Secretario Nivel 2
create table if not exists public.convites_secretario_n2 (
    id bigserial primary key,
    token text not null unique,
    telegram_id_destino bigint not null,
    nivel_alvo text not null default '2',
    status text not null default 'ativo',
    criado_por bigint not null,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at timestamptz null
);

create index if not exists idx_convites_secretario_n2_destino
    on public.convites_secretario_n2 (telegram_id_destino);

create index if not exists idx_convites_secretario_n2_status
    on public.convites_secretario_n2 (status);
