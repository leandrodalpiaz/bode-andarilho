-- Criar tabela de marcos coletivos (expansão, conquistas e recordes)
create table if not exists public.marcos_coletivos (
    marco_slug text primary key,
    categoria text not null,
    criado_em timestamptz not null default now()
);

-- Indexação para listagem por categoria/tipo rápida
create index if not exists idx_marcos_coletivos_categoria on public.marcos_coletivos (categoria);
