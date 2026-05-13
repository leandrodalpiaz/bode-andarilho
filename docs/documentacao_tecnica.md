# Documentacao Tecnica - Bode Andarilho Bot

**Versao:** 2.2 (Supabase + Mini App + Cards Visuais)
**Ultima atualizacao:** 13/05/2026
**Runtime:** Python 3.12

## 1. Visao Geral

O **Bode Andarilho** e um bot do Telegram para gerenciar eventos/sessoes,
presencas e membros.

A logica de confirmacao, cancelamento, listagem de confirmados, links de
endereco, captions, callbacks e botoes inline permanece fora da renderizacao
visual. A camada de cards apenas gera a imagem usada na publicacao.

Pontos-chave:

- Fluxos principais preferem Mini App (formularios) para reduzir erro de digitacao.
- Publicacao de evento no grupo pode ser foto/card com botoes inline abaixo.
- Fallback obrigatorio: se renderizacao/envio de imagem falhar, publica em texto.

## 2. Arquitetura e Tecnologias

- python-telegram-bot (handlers, callbacks, envio/edicao de mensagens)
- Starlette + uvicorn (webhook e Mini App HTTP)
- Supabase (PostgreSQL + Storage)
- APScheduler (jobs recorrentes)
- Pillow (renderizacao de cards)

## 3. Estrutura de Diretorios

```text
assets/
  branding/              # marca d'agua opcional do Bode Andarilho
  fonts/                 # fontes .ttf usadas no card padrao
  potencias/             # selos GOB/CMSB/COMAB
  stamps/                # selos de grau (aprendiz/companheiro/mestre)
  templates/             # templates, incluindo o default do sistema
docs/
  supabase_event_cards.sql
  supabase_potencias_normalizadas.sql
src/
  miniapp.py
  render_cards.py        # renderizador de cards com Pillow
  evento_midia.py        # decisao: card especial / template / texto fallback
  sheets_supabase.py
  potencias.py
  ajuda/
main.py
```

## 4. Camada Visual de Eventos

Regra operacional:

1. Se o evento tiver `card_especial_url`, publica o card especial.
2. Senao, se houver template da Loja, renderiza com o template da Loja.
3. Senao, usa o template padrao do sistema.
4. Se qualquer etapa visual falhar, usa texto fallback.

Essa camada nao altera:

- callbacks `confirmar|`, `cancelar_card|`, `ver_confirmados|`;
- botoes inline do Telegram;
- regras de confirmacao/cancelamento;
- link de endereco/Google Maps;
- scheduler/lembretes;
- permissoes;
- banco de dados.

## 5. Template Padrao do Sistema

Arquivo:

```text
assets/templates/default_event_card.png
```

Uso:

- sugerido automaticamente quando a Loja nao tiver template visual proprio;
- funciona como fallback institucional;
- mantem a comunicacao visual mesmo em homologacao ou lojas recem-cadastradas.

Montagem visual atual em `src/render_cards.py`:

1. Topo esquerdo: selo da potencia em `assets/potencias/` e complemento pequeno.
2. Topo direito: carimbo do grau em `assets/stamps/`.
3. Data/hora centralizadas, com hora em peso visual maior.
4. Linha discreta de grau no corpo.
5. Secao `LOJA`: nome, numero destacado, cidade, UF e potencia/complemento.
6. Secao `SESSAO`: tipo de sessao, rito, traje e agape.
7. Secao `ORDEM DO DIA / OBSERVACOES`: pauta com quebra automatica.
8. Rodape: frase institucional discreta.

Regras visuais consolidadas:

- O texto "Nova Sessao" nao e renderizado.
- O rito nao aparece no topo.
- O rito aparece apenas dentro da secao `SESSAO`.
- Links e botoes ficam fora da imagem, no Telegram.

## 6. Marca d'agua opcional

Arquivo reconhecido:

```text
assets/branding/bode_andarilho_watermark.png
```

Comportamento:

- aplicada somente no template padrao;
- opacidade baixa;
- tratamento em sepia;
- tentativa de remocao de fundo claro;
- posicionamento discreto no centro-direita;
- sem impacto funcional.

Formato recomendado:

- PNG;
- fundo transparente;
- 800x800 a 1200x1200 px;
- estilo gravura/traco;
- sem textos que concorram com os dados da sessao.

## 7. Como editar no futuro

Para trocar apenas o fundo, substitua:

```text
assets/templates/default_event_card.png
```

Para trocar selos sem alterar codigo:

```text
assets/stamps/aprendiz.png
assets/stamps/companheiro.png
assets/stamps/mestre.png
assets/potencias/gob.png
assets/potencias/cmsb.png
assets/potencias/comab.png
assets/branding/bode_andarilho_watermark.png
```

Para ajustar hierarquia, espacamentos, fontes, opacidade ou posicoes, editar
somente o bloco do template padrao em `src/render_cards.py`.

## 8. Potencias

Padrao oficial:

- `potencia`: apenas `GOB`, `CMSB` ou `COMAB`
- `potencia_complemento`: texto livre obrigatorio para todas

Exemplos de complemento:

- `GOB-RS`
- `GLMERGS`
- `GORGS`
- `GOSC`
- `GOP`

## 9. Supabase

Scripts SQL em `docs/`:

- `supabase_event_cards.sql`
- `supabase_potencias_normalizadas.sql`

Bucket recomendado:

```text
event-cards
```

Estrutura logica:

- `lojas/{loja_id}/template.*`
- `eventos/{id_evento}/render.png`
- `eventos/{id_evento}/especial.*`

## 10. Verificacao rapida

```bash
python -m compileall main.py src
```

## 11. Referencias

- Fluxos atualizados: `docs/fluxos_atualizados_2026_04.md`
- Ajuda/FAQ: `src/ajuda/faq.py`
- Manutencao da base de IA/ajuda: `docs/manutencao_ajuda_e_ia.md`
