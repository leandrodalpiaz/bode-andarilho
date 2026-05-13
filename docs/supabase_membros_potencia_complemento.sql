-- Adiciona suporte ao complemento de potência no cadastro de membros.
-- Seguro para produção: idempotente e com backfill.

alter table if exists public.membros
  add column if not exists potencia_complemento text default '';

update public.membros
set potencia_complemento = coalesce(potencia_complemento, '')
where potencia_complemento is null;

