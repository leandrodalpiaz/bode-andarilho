# Bode Andarilho

Bot Telegram para gerenciamento de eventos, confirmacoes e membros, com backend em Python e persistencia em Supabase.

## Documentacao principal

- Documentacao tecnica: `docs/documentacao_tecnica.md`
- Fluxos atualizados (estado real do codigo): `docs/fluxos_atualizados_2026_04.md`
- Base estruturada para camada de IA: `docs/ajuda_ia_base.yaml`
- Guia de manutencao de ajuda + IA: `docs/manutencao_ajuda_e_ia.md`

## Stack

- Python 3.12
- python-telegram-bot
- Starlette + uvicorn
- Supabase (PostgreSQL)
- APScheduler

## Execucao

```bash
python main.py
```

## Observacao

A migracao de Google Sheets para Supabase foi concluida em 10/03/2026.
Consulte a secao de migracao em `docs/documentacao_tecnica.md`.
