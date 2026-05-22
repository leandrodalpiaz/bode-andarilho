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
    logo_url text,
    imagem_publicidade_url text,
    status text not null default 'ativo',
    observacoes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.apoiadores
    add column if not exists logo_url text;
alter table public.apoiadores
    add column if not exists imagem_publicidade_url text;

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
    periodicidade text not null default 'mensal',
    dia_vencimento integer not null default 10,
    renovacao_alerta_dias integer not null default 30,
    termo_url text,
    observacoes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.apoios_contratos
    add column if not exists periodicidade text default 'mensal';
alter table public.apoios_contratos
    add column if not exists dia_vencimento integer default 10;
alter table public.apoios_contratos
    add column if not exists renovacao_alerta_dias integer default 30;

update public.apoios_contratos
set periodicidade = coalesce(periodicidade, 'mensal'),
    dia_vencimento = coalesce(dia_vencimento, 10),
    renovacao_alerta_dias = coalesce(renovacao_alerta_dias, 30);

alter table public.apoios_contratos
    alter column periodicidade set not null,
    alter column dia_vencimento set not null,
    alter column renovacao_alerta_dias set not null;

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
    drop constraint if exists apoios_contratos_periodicidade_check;
alter table public.apoios_contratos
    add constraint apoios_contratos_periodicidade_check
    check (periodicidade in ('mensal', 'trimestral', 'semestral', 'anual', 'avulso'));

alter table public.apoios_contratos
    drop constraint if exists apoios_contratos_dia_vencimento_check;
alter table public.apoios_contratos
    add constraint apoios_contratos_dia_vencimento_check
    check (dia_vencimento between 1 and 31);

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

create table if not exists public.apoios_pagamentos (
    id uuid primary key default gen_random_uuid(),
    apoiador_id uuid not null references public.apoiadores(id) on delete cascade,
    contrato_id uuid references public.apoios_contratos(id) on delete set null,
    competencia text not null,
    data_vencimento date,
    valor_previsto numeric(12,2) not null default 0,
    valor_pago numeric(12,2) not null default 0,
    data_pagamento date,
    status text not null default 'pendente',
    forma_pagamento text,
    comprovante_url text,
    observacoes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.apoios_pagamentos
    drop constraint if exists apoios_pagamentos_status_check;
alter table public.apoios_pagamentos
    add constraint apoios_pagamentos_status_check
    check (status in ('pendente', 'pago', 'parcial', 'atrasado', 'cancelado'));

alter table public.apoios_pagamentos
    drop constraint if exists apoios_pagamentos_competencia_check;
alter table public.apoios_pagamentos
    add constraint apoios_pagamentos_competencia_check
    check (competencia ~ '^[0-9]{4}-[0-9]{2}$');

create table if not exists public.apoios_criativos (
    id uuid primary key default gen_random_uuid(),
    apoiador_id uuid not null references public.apoiadores(id) on delete cascade,
    contrato_id uuid references public.apoios_contratos(id) on delete set null,
    tipo_posicionamento text not null,
    titulo text,
    texto text,
    imagem_url text,
    link_url text,
    status text not null default 'ativo',
    prioridade integer not null default 1,
    data_inicio date,
    data_fim date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.apoios_criativos
    drop constraint if exists apoios_criativos_tipo_check;
alter table public.apoios_criativos
    add constraint apoios_criativos_tipo_check
    check (tipo_posicionamento in (
        'card_logo',
        'rodape_diploma',
        'tela_apoiadores',
        'ia_resposta_texto',
        'confirmados_premium_texto'
    ));

alter table public.apoios_criativos
    drop constraint if exists apoios_criativos_status_check;
alter table public.apoios_criativos
    add constraint apoios_criativos_status_check
    check (status in ('ativo', 'pausado', 'encerrado'));

alter table public.apoios_criativos
    drop constraint if exists apoios_criativos_periodo_check;
alter table public.apoios_criativos
    add constraint apoios_criativos_periodo_check
    check (data_fim is null or data_inicio is null or data_fim >= data_inicio);

alter table public.apoios_exibicoes
    drop constraint if exists apoios_exibicoes_tipo_check;
alter table public.apoios_exibicoes
    add constraint apoios_exibicoes_tipo_check
    check (tipo_exibicao in (
        'card_logo',
        'confirmados_premium_texto',
        'ia_resposta_texto',
        'rodape_diploma',
        'rodape_textual',
        'botao_apoiadores',
        'menu_inicial',
        'tela_apoiadores'
    ));

create index if not exists idx_apoiadores_status on public.apoiadores(status);
create index if not exists idx_apoios_contratos_apoiador on public.apoios_contratos(apoiador_id);
create index if not exists idx_apoios_contratos_vigencia on public.apoios_contratos(data_inicio, data_fim, status);
create index if not exists idx_apoios_exibicoes_apoiador_tipo_data on public.apoios_exibicoes(apoiador_id, tipo_exibicao, created_at);
create index if not exists idx_apoios_pagamentos_competencia_status on public.apoios_pagamentos(competencia, status);
create index if not exists idx_apoios_pagamentos_contrato on public.apoios_pagamentos(contrato_id);
create index if not exists idx_apoios_criativos_tipo_status on public.apoios_criativos(tipo_posicionamento, status);
create index if not exists idx_apoios_criativos_apoiador on public.apoios_criativos(apoiador_id);
