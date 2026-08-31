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
- React + TypeScript + Vite (PWA em `web/`)

## PWA em coexistência gradual

O shell da PWA é servido pela mesma aplicação Starlette quando `web/dist` existe.
O backend expõe a API v1 em `/api/v1`; o navegador usa apenas a chave publicável
do Supabase e envia escritas para o backend. Telegram continua sendo o canal
legado durante a construção e o piloto.

O schema novo está em `pwa_v2` e não reutiliza as tabelas legadas. A migration
`supabase/migrations/20260831165939_create_pwa_v2.sql` é versionada e foi
validada apenas no Supabase local; não foi aplicada automaticamente a nenhum
ambiente remoto.

## Execução

```bash
python main.py
```

Para validar o frontend:

```bash
cd web
npm ci
npm run typecheck
npm run build
```

## Assets (camada visual)

- Template padrão do sistema: `assets/templates/default_event_card.png`
- Selos de grau (carimbos): `assets/stamps/`
- Selos de potência (GOB/CMSB/COMAB): `assets/potencias/`
- Fontes versionadas usadas no card padrão: `assets/fonts/`
- Marca d'água opcional: `assets/branding/bode_andarilho_watermark.png`

Quando a Loja não possui template próprio, o bot usa o template padrão do sistema
e mantém links, captions e botões inline do Telegram fora da imagem.

## Migrações Supabase

Os scripts SQL ficam em `docs/` e devem ser aplicados no ambiente quando necessário:

- `docs/supabase_event_cards.sql` (colunas de camada visual do evento/loja)
- `docs/supabase_potencias_normalizadas.sql` (normalização de potência + complemento)
