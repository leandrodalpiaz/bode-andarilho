-- Otimiza a avaliação de auth.uid() nas políticas próprias de perfil.
-- A expressão escalar é calculada uma vez por instrução, não uma vez por linha.

drop policy if exists perfis_select_own_or_global on pwa_v2.perfis;
create policy perfis_select_own_or_global on pwa_v2.perfis
    for select to authenticated
    using ((select auth.uid()) = auth_user_id or pwa_private.is_global_admin());

drop policy if exists perfis_update_own on pwa_v2.perfis;
create policy perfis_update_own on pwa_v2.perfis
    for update to authenticated
    using ((select auth.uid()) = auth_user_id)
    with check ((select auth.uid()) = auth_user_id);
