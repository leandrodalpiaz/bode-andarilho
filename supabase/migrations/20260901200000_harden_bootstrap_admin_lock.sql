-- Serializa o primeiro bootstrap global para que duas requisições concorrentes
-- não ultrapassem a checagem de ausência de administrador.
create or replace function pwa_private.bootstrap_admin(
    target_auth_user_id uuid,
    authenticated_email text,
    display_name text,
    request_uuid uuid
)
returns jsonb
language plpgsql
security definer
set search_path = pwa_v2, pg_catalog
as $$
declare
    target_profile_id uuid;
begin
    perform pg_advisory_xact_lock(
        hashtextextended('pwa_v2.bootstrap_admin', 0)
    );

    if target_auth_user_id is null or authenticated_email is null then
        raise exception using errcode = '22023', message = 'Dados do administrador incompletos';
    end if;
    if exists (
        select 1 from pwa_v2.vinculos_loja
         where loja_id is null and papel = 'admin'
    ) then
        raise exception using errcode = 'P0001', message = 'Administrador inicial já configurado';
    end if;

    select p.id into target_profile_id
      from pwa_v2.perfis p
     where p.auth_user_id = target_auth_user_id
     for update;

    if target_profile_id is null then
        insert into pwa_v2.perfis (auth_user_id, nome, email, status)
        values (
            target_auth_user_id,
            coalesce(nullif(btrim(display_name), ''), split_part(lower(btrim(authenticated_email)), '@', 1)),
            lower(btrim(authenticated_email)),
            'active'
        )
        returning id into target_profile_id;
    else
        update pwa_v2.perfis
           set nome = coalesce(nullif(btrim(display_name), ''), nome),
               email = lower(btrim(authenticated_email)),
               status = 'active',
               updated_at = now()
         where id = target_profile_id;
    end if;

    insert into pwa_v2.vinculos_loja (perfil_id, loja_id, papel, status)
    values (target_profile_id, null, 'admin', 'active');

    insert into pwa_v2.auditoria (
        ator_perfil_id, acao, entidade_tipo, entidade_id, origem, request_id, metadata
    ) values (
        target_profile_id, 'admin_bootstrapped', 'perfis', target_profile_id::text, 'bootstrap', request_uuid, '{}'::jsonb
    );

    return jsonb_build_object('perfil_id', target_profile_id, 'papel', 'admin');
end
$$;
