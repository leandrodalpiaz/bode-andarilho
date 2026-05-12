# Bode Andarilho

Bot Telegram para gerenciamento de eventos/sessões, confirmações e membros, com backend em Python e persistência em Supabase.

O bot preserva a lógica existente de confirmação/cancelamento/ver confirmados, e evolui a camada de apresentação:
eventos podem ser publicados no grupo como imagem (card) com os botões inline do Telegram abaixo.

## Documentação principal

- Documentação técnica: `docs/documentacao_tecnica.md`
- Fluxos atualizados (estado real do código): `docs/fluxos_atualizados_2026_04.md`
- Base estruturada para camada de IA/ajuda: `docs/ajuda_ia_base.yaml`
- Guia de manutenção de ajuda + IA: `docs/manutencao_ajuda_e_ia.md`

## Stack

- Python 3.12
- python-telegram-bot
- Starlette + uvicorn (webhook)
- Supabase (PostgreSQL + Storage)
- APScheduler
- Pillow (renderização de cards)

## Execução

```bash
python main.py
```

## Assets (camada visual)

- Template padrão do sistema: `assets/templates/default_event_card.png`
- Selos de grau (carimbos): `assets/stamps/`
- Selos de potência (GOB/CMSB/COMAB): `assets/potencias/`
- Fontes versionadas usadas no card padrão: `assets/fonts/`

## Migrações Supabase

Os scripts SQL ficam em `docs/` e devem ser aplicados no ambiente quando necessário:

- `docs/supabase_event_cards.sql` (colunas de camada visual do evento/loja)
- `docs/supabase_potencias_normalizadas.sql` (normalização de potência + complemento)

