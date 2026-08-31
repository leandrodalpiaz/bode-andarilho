-- Associação opcional de um canal externo a um perfil já autenticado.
-- A migration é aditiva e não toca nas tabelas legadas.

create table if not exists pwa_v2.codigos_associacao (
    id uuid primary key default extensions.gen_random_uuid(),
    perfil_id uuid not null references pwa_v2.perfis(id) on delete cascade,
    provedor text not null check (provedor in ('telegram')),
    codigo_hash text not null unique,
    idempotency_key_hash text not null,
    valid_until timestamptz not null,
    consumed_at timestamptz,
    consumed_external_user_id text,
    created_at timestamptz not null default now(),
    check ((consumed_at is null) = (consumed_external_user_id is null)),
    unique (perfil_id, idempotency_key_hash)
);

create index if not exists codigos_associacao_perfil_idx
    on pwa_v2.codigos_associacao (perfil_id);
create index if not exists codigos_associacao_valid_until_idx
    on pwa_v2.codigos_associacao (valid_until)
    where consumed_at is null;

create or replace function pwa_private.consume_external_identity(
    association_code_hash text,
    target_provider text,
    external_user_id_value text,
    request_uuid uuid
)
returns jsonb
language plpgsql
security definer
set search_path = pwa_v2, pg_catalog
as $$
declare
    code_row pwa_v2.codigos_associacao%rowtype;
    target_profile pwa_v2.perfis%rowtype;
begin
    if association_code_hash is null
       or lower(btrim(target_provider)) <> 'telegram'
       or external_user_id_value is null
       or btrim(external_user_id_value) = '' then
        raise exception using errcode = '22023', message = 'Dados de associação incompletos';
    end if;

    select *
      into code_row
      from pwa_v2.codigos_associacao
     where codigo_hash = association_code_hash
       and provedor = lower(btrim(target_provider))
     for update;

    if not found then
        raise exception using errcode = 'P0001', message = 'Código de associação inválido';
    end if;
    if code_row.consumed_at is not null then
        raise exception using errcode = 'P0001', message = 'Código de associação já consumido';
    end if;
    if code_row.valid_until <= now() then
        raise exception using errcode = 'P0001', message = 'Código de associação expirado';
    end if;

    select *
      into target_profile
      from pwa_v2.perfis
     where id = code_row.perfil_id
     for update;

    if not found or target_profile.status <> 'active' then
        raise exception using errcode = 'P0001', message = 'Perfil de associação indisponível';
    end if;
    if exists (
        select 1
          from pwa_v2.identidades_externas
         where provedor = lower(btrim(target_provider))
           and external_user_id = btrim(external_user_id_value)
    ) then
        raise exception using errcode = 'P0001', message = 'Identidade externa já associada';
    end if;

    insert into pwa_v2.identidades_externas (
        perfil_id, provedor, external_user_id, metadata
    ) values (
        target_profile.id,
        lower(btrim(target_provider)),
        btrim(external_user_id_value),
        jsonb_build_object('association_code_id', code_row.id)
    );

    update pwa_v2.codigos_associacao
       set consumed_at = now(),
           consumed_external_user_id = btrim(external_user_id_value)
     where id = code_row.id;

    insert into pwa_v2.auditoria (
        ator_perfil_id, acao, entidade_tipo, entidade_id, origem, request_id, metadata
    ) values (
        target_profile.id,
        'external_identity_associated',
        'identidades_externas',
        target_profile.id::text,
        'telegram',
        request_uuid,
        jsonb_build_object('provedor', lower(btrim(target_provider)))
    );

    return jsonb_build_object(
        'perfil_id', target_profile.id,
        'provedor', lower(btrim(target_provider)),
        'external_user_id', btrim(external_user_id_value)
    );
end
$$;

create or replace function pwa_v2.consume_external_identity(
    association_code_hash text,
    target_provider text,
    external_user_id_value text,
    request_uuid uuid
)
returns jsonb
language sql
security invoker
set search_path = pwa_v2, pg_catalog
as $$
    select pwa_private.consume_external_identity($1, $2, $3, $4)
$$;

revoke all on function pwa_private.consume_external_identity(text, text, text, uuid)
    from public, anon, authenticated;
revoke all on function pwa_v2.consume_external_identity(text, text, text, uuid)
    from public, anon, authenticated;
grant execute on function pwa_private.consume_external_identity(text, text, text, uuid)
    to service_role;
grant execute on function pwa_v2.consume_external_identity(text, text, text, uuid)
    to service_role;

alter table pwa_v2.codigos_associacao enable row level security;
alter table pwa_v2.codigos_associacao force row level security;

-- O código nunca é lido diretamente pelo navegador; geração e consumo passam
-- pelo backend com service_role e pelas validações acima.
revoke all on pwa_v2.codigos_associacao from public, anon, authenticated, service_role;
grant all privileges on pwa_v2.codigos_associacao to service_role;
