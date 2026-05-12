-- Camada visual de eventos (templates/cards)
-- Execute este script no SQL Editor do Supabase.

alter table if exists public.lojas
    add column if not exists template_sessao_url text,
    add column if not exists layout_config_json text,
    add column if not exists cor_texto_padrao text,
    add column if not exists fonte_padrao text,
    add column if not exists cor_selo_grau text,
    add column if not exists cor_selo_rito text,
    add column if not exists cor_selo_potencia text,
    add column if not exists status_template text;

alter table if exists public.eventos
    add column if not exists modo_visual text,
    add column if not exists card_especial_url text,
    add column if not exists card_renderizado_url text,
    add column if not exists card_file_id_telegram text,
    add column if not exists telegram_tipo_mensagem_grupo text;

create index if not exists idx_eventos_modo_visual
    on public.eventos (modo_visual);

create index if not exists idx_lojas_status_template
    on public.lojas (status_template);

-- Bucket recomendado no Supabase Storage:
-- event-cards
--
-- Pastas lógicas:
-- lojas/{loja_id}/template.*
-- eventos/{id_evento}/render.png
-- eventos/{id_evento}/especial.*
