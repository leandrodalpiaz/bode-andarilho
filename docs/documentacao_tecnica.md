# Documentacao Tecnica - Bode Andarilho Bot

**Versao:** 2.1 (Supabase + Mini App + Cards Visuais)
**Ultima atualizacao:** 12/05/2026
**Runtime:** Python 3.12

## 1. Visao Geral

O **Bode Andarilho** e um bot do Telegram para gerenciar eventos/sessoes, presencas e membros.
A logica de confirmacao/cancelamento e os callbacks existentes foram preservados; a evolucao principal recente foi na camada de apresentacao e padronizacao de cadastros via Mini App.

Pontos-chave:

- Fluxos principais preferem Mini App (formularios) para reduzir erros de digitacao e padronizar dados.
- Publicacao de evento no grupo pode ser uma foto (card) com botoes inline abaixo (`send_photo(..., reply_markup=...)`).
- Fallback obrigatorio: se falhar renderizacao/envio de imagem, publica em texto (com a mesma logica atual).

## 2. Arquitetura e Tecnologias

- python-telegram-bot (handlers, callbacks, envio/edicao de mensagens)
- Starlette + uvicorn (webhook e Mini App HTTP)
- Supabase (PostgreSQL + Storage)
- APScheduler (jobs recorrentes)
- Pillow (renderizacao de cards)

## 3. Estrutura de Diretorios (alto nivel)

```text
assets/
  fonts/                 # fontes .ttf usadas no card padrao
  potencias/             # selos GOB/CMSB/COMAB
  stamps/                # selos de grau (aprendiz/companheiro/mestre)
  templates/             # templates, incluindo o default do sistema
docs/
  supabase_event_cards.sql
  supabase_potencias_normalizadas.sql
src/
  miniapp.py             # endpoints do Mini App e validacao initData
  render_cards.py        # renderizador de cards com Pillow
  evento_midia.py        # decisao: card especial / template / texto fallback
  sheets_supabase.py     # camada de dados (Supabase REST) + mapeamentos
  potencias.py           # normalizacao/validacao de potencia + complemento
  ajuda/                 # FAQ, tutoriais, glossario e menus de ajuda
main.py                  # webhook Telegram + inicializacao do app
```

## 4. Camada Visual de Eventos (MVP)

Regra operacional:

1. Se o evento tiver `card_especial_url`, publica o card especial.
2. Senao, se houver template (da loja ou default), renderiza um card e publica como foto.
3. Senao, publica no formato textual atual.

O card padrao do sistema usa:

- `assets/templates/default_event_card.png`
- fontes versionadas em `assets/fonts`
- selo de grau no canto superior direito (carimbo) a partir de `assets/stamps`
- selo de potencia no canto superior esquerdo a partir de `assets/potencias`, com `potencia_complemento` exibido pequeno

Importante:

- Links (ex.: Google Maps) e os botoes de confirmacao/cancelamento/ver confirmados ficam fora da imagem (caption e teclado inline do Telegram).
- A camada visual e aditiva. O bot nao pode deixar de comunicar evento por falha de imagem.

## 5. Potencias (normalizacao)

Padrao oficial:

- `potencia`: apenas `GOB`, `CMSB` ou `COMAB`
- `potencia_complemento`: texto livre obrigatorio para **todas** (ex.: `GOB-RS`, `GLMERGS`, `GORGS`, `GOSC`, `GOP`)

O Mini App e o backend validam a regra; eventos podem herdar potencia/complemento da Loja quando aplicavel.

## 6. Supabase (DB + Storage)

### 6.1 Migracoes SQL

Arquivos em `docs/`:

- `supabase_event_cards.sql`: colunas de camada visual (lojas/eventos)
- `supabase_potencias_normalizadas.sql`: colunas `*_potencia_complemento` + normalizacao de valores legados

### 6.2 Storage

Bucket recomendado: `event-cards` (estrutura logica):

- `lojas/{loja_id}/template.*`
- `eventos/{id_evento}/render.png`
- `eventos/{id_evento}/especial.*`

## 7. Execucao / Verificacao rapida

```bash
python -m compileall main.py src
python main.py
```

## 8. Referencias de Fluxo

- Fluxos atualizados: `docs/fluxos_atualizados_2026_04.md`
- Ajuda/FAQ (no bot): `src/ajuda/faq.py`
- Manutencao da base de IA/ajuda: `docs/manutencao_ajuda_e_ia.md`

