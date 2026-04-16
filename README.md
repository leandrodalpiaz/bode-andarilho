# Bode Andarilho

Bot Telegram para gerenciamento de eventos, confirmações e membros, com backend em Python e persistência em Supabase.

## Documentação principal

- Documentação técnica: `docs/documentacao_tecnica.md`
- Fluxos atualizados (estado real do código): `docs/fluxos_atualizados_2026_04.md`
- Base estruturada para camada de IA: `docs/ajuda_ia_base.yaml`
- Guia de manutenção de ajuda + IA: `docs/manutencao_ajuda_e_ia.md`

## Stack

- Python 3.12
- python-telegram-bot
- Starlette + uvicorn
- Supabase (PostgreSQL)
- APScheduler

## Execução

```bash
python main.py
```

## Observação

A migração de Google Sheets para Supabase foi concluída em 10/03/2026.
Consulte a seção de migração em `docs/documentacao_tecnica.md`.
