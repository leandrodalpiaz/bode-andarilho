# Documentação Técnica - Bode Andarilho Bot

**Versão:** 2.1 (Supabase + Mini App + Cards Visuais)
**Última atualização:** 12/05/2026
**Runtime:** Python 3.12

## 1. Visão Geral

O **Bode Andarilho** é um bot do Telegram para gerenciar eventos/sessões, presenças e membros.
A lógica de confirmação/cancelamento e os callbacks existentes foram preservados; a evolução principal recente foi na camada de apresentação e padronização de cadastros via Mini App.

Pontos-chave:

- Fluxos principais preferem Mini App (formulários) para reduzir erros de digitação e padronizar dados.
- Publicação de evento no grupo pode ser uma foto (card) com botões inline abaixo (`send_photo(..., reply_markup=...)`).
- Fallback obrigatório: se falhar renderização/envio de imagem, publica em texto (com a mesma lógica atual).

## 2. Arquitetura e Tecnologias

- python-telegram-bot (handlers, callbacks, envio/edicao de mensagens)
- Starlette + uvicorn (webhook e Mini App HTTP)
- Supabase (PostgreSQL + Storage)
- APScheduler (jobs recorrentes)
- Pillow (renderização de cards)

## 3. Estrutura de Diretórios (alto nível)

```text
assets/
  fonts/                 # fontes .ttf usadas no card padrão
  potencias/             # selos GOB/CMSB/COMAB
  stamps/                # selos de grau (aprendiz/companheiro/mestre)
  templates/             # templates, incluindo o default do sistema
docs/
  supabase_event_cards.sql
  supabase_potencias_normalizadas.sql
src/
  miniapp.py             # endpoints do Mini App e validação initData
  render_cards.py        # renderizador de cards com Pillow
  evento_midia.py        # decisão: card especial / template / texto fallback
  sheets_supabase.py     # camada de dados (Supabase REST) + mapeamentos
  potencias.py           # normalização/validação de potência + complemento
  ajuda/                 # FAQ, tutoriais, glossário e menus de ajuda
main.py                  # webhook Telegram + inicialização do app
```

## 4. Camada Visual de Eventos (MVP)

Regra operacional:

1. Se o evento tiver `card_especial_url`, publica o card especial.
2. Senão, se houver template (da loja ou default), renderiza um card e publica como foto.
3. Senão, publica no formato textual atual.

O card padrão do sistema usa:

- `assets/templates/default_event_card.png`
- fontes versionadas em `assets/fonts`
- selo de grau no canto superior direito (carimbo) a partir de `assets/stamps`
- selo de potência no canto superior esquerdo a partir de `assets/potencias`, com `potencia_complemento` exibido pequeno

Importante:

- Links (ex.: Google Maps) e os botões de confirmação/cancelamento/ver confirmados ficam fora da imagem (caption e teclado inline do Telegram).
- A camada visual é aditiva. O bot não pode deixar de comunicar evento por falha de imagem.

## 5. Potências (normalização)

Padrão oficial:

- `potencia`: apenas `GOB`, `CMSB` ou `COMAB`
- `potencia_complemento`: texto livre obrigatório para **todas** (ex.: `GOB-RS`, `GLMERGS`, `GORGS`, `GOSC`, `GOP`)

O Mini App e o backend validam a regra; eventos podem herdar potência/complemento da Loja quando aplicável.

## 6. Supabase (DB + Storage)

### 6.1 Migrações SQL

Arquivos em `docs/`:

- `supabase_event_cards.sql`: colunas de camada visual (lojas/eventos)
- `supabase_potencias_normalizadas.sql`: colunas `*_potencia_complemento` + normalização de valores legados

### 6.2 Storage

Bucket recomendado: `event-cards` (estrutura lógica):

- `lojas/{loja_id}/template.*`
- `eventos/{id_evento}/render.png`
- `eventos/{id_evento}/especial.*`

## 7. Execução / Verificação rápida

```bash
python -m compileall main.py src
python main.py
```

## 8. Referências de Fluxo

- Fluxos atualizados: `docs/fluxos_atualizados_2026_04.md`
- Ajuda/FAQ (no bot): `src/ajuda/faq.py`
- Manutenção da base de IA/ajuda: `docs/manutencao_ajuda_e_ia.md`

