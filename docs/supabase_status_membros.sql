-- Status de cadastro de membros (ativo/inativo/pendente validacao)
-- Execute este script no SQL Editor do Supabase.

alter table if exists public.membros
    add column if not exists status text;

-- Retrocompatibilidade: registros antigos sem status passam a ativos.
update public.membros
set status = 'Ativo'
where status is null or btrim(status) = '';

-- Mantem padrao para novos cadastros.
alter table if exists public.membros
    alter column status set default 'Ativo';

create index if not exists idx_membros_status
    on public.membros (status);
