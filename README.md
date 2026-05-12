# Bode Andarilho

Bot Telegram para gerenciamento de eventos/sessoes, confirmacoes e membros, com backend em Python e persistencia em Supabase.

O bot preserva a logica existente de confirmacao/cancelamento/ver confirmados, e evolui a camada de apresentacao:
eventos podem ser publicados no grupo como imagem (card) com os botoes inline do Telegram abaixo.

## Documentacao principal

- Documentacao tecnica: `docs/documentacao_tecnica.md`
- Fluxos atualizados (estado real do codigo): `docs/fluxos_atualizados_2026_04.md`
- Base estruturada para camada de IA/ajuda: `docs/ajuda_ia_base.yaml`
- Guia de manutencao de ajuda + IA: `docs/manutencao_ajuda_e_ia.md`

## Stack

- Python 3.12
- python-telegram-bot
- Starlette + uvicorn (webhook)
- Supabase (PostgreSQL + Storage)
- APScheduler
- Pillow (renderizacao de cards)

## Execucao

```bash
python main.py
```

## Assets (camada visual)

- Template padrao do sistema: `assets/templates/default_event_card.png`
- Selos de grau (carimbos): `assets/stamps/`
- Selos de potencia (GOB/CMSB/COMAB): `assets/potencias/`
- Fontes versionadas usadas no card padrao: `assets/fonts/`

## Migracoes Supabase

Os scripts SQL ficam em `docs/` e devem ser aplicados no ambiente quando necessario:

- `docs/supabase_event_cards.sql` (colunas de camada visual do evento/loja)
- `docs/supabase_potencias_normalizadas.sql` (normalizacao de potencia + complemento)

