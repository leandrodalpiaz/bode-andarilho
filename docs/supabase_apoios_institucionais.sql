create table if not exists public.apoiadores (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    responsavel_nome text,
    telefone text,
    email text,
    segmento text,
    cidade text,
    link_publico text,
    texto_curto text,
    status text not null default 'ativo',
    observacoes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.apoiadores
    drop constraint if exists apoiadores_status_check;
alter table public.apoiadores
    add constraint apoiadores_status_check
    check (status in ('ativo', 'pausado', 'encerrado'));

create table if not exists public.apoios_contratos (
    id uuid primary key default gen_random_uuid(),
    apoiador_id uuid not null references public.apoiadores(id) on delete cascade,
    categoria text not null,
    data_inicio date not null,
    data_fim date not null,
    valor_contribuicao numeric(12,2),
    finalidade text,
    status text not null default 'ativo',
    termo_url text,
    observacoes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.apoios_contratos
    drop constraint if exists apoios_contratos_categoria_check;
alter table public.apoios_contratos
    add constraint apoios_contratos_categoria_check
    check (categoria in ('master', 'destaque', 'institucional', 'amigo_projeto'));

alter table public.apoios_contratos
    drop constraint if exists apoios_contratos_status_check;
alter table public.apoios_contratos
    add constraint apoios_contratos_status_check
    check (status in ('ativo', 'vencido', 'pausado', 'encerrado', 'inadimplente'));

alter table public.apoios_contratos
    drop constraint if exists apoios_contratos_periodo_check;
alter table public.apoios_contratos
    add constraint apoios_contratos_periodo_check
    check (data_fim >= data_inicio);

create table if not exists public.apoios_config (
    id uuid primary key default gen_random_uuid(),
    apoiador_id uuid not null references public.apoiadores(id) on delete cascade,
    permite_logo_card boolean not null default false,
    permite_confirmados boolean not null default false,
    permite_ia boolean not null default false,
    permite_rodape boolean not null default false,
    permite_botao_link boolean not null default true,
    limite_card_mes integer not null default 0,
    limite_confirmados_mes integer not null default 0,
    limite_ia_mes integer not null default 0,
    limite_rodape_mes integer not null default 0,
    peso_prioridade integer not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.apoios_exibicoes (
    id uuid primary key default gen_random_uuid(),
    apoiador_id uuid not null references public.apoiadores(id) on delete cascade,
    contrato_id uuid references public.apoios_contratos(id) on delete set null,
    tipo_exibicao text not null,
    contexto text,
    evento_id text,
    usuario_id bigint,
    created_at timestamptz not null default now()
);

alter table public.apoios_exibicoes
    drop constraint if exists apoios_exibicoes_tipo_check;
alter table public.apoios_exibicoes
    add constraint apoios_exibicoes_tipo_check
    check (tipo_exibicao in (
        'card_logo',
        'confirmados_premium_texto',
        'ia_resposta_texto',
        'rodape_textual',
        'botao_apoiadores',
        'menu_inicial',
        'tela_apoiadores'
    ));

create index if not exists idx_apoiadores_status on public.apoiadores(status);
create index if not exists idx_apoios_contratos_apoiador on public.apoios_contratos(apoiador_id);
create index if not exists idx_apoios_contratos_vigencia on public.apoios_contratos(data_inicio, data_fim, status);
create index if not exists idx_apoios_exibicoes_apoiador_tipo_data on public.apoios_exibicoes(apoiador_id, tipo_exibicao, created_at);
