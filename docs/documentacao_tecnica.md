# Documentação Técnica - Bode Andarilho Bot

**Versão:** 2.2 (Supabase + Mini App + Cards Visuais)
**Última atualização:** 13/05/2026
**Runtime:** Python 3.12

## 1. Visão Geral

O **Bode Andarilho** é um bot do Telegram para gerenciar eventos/sessões,
presenças e membros.

A lógica de confirmação, cancelamento, listagem de confirmados, links de
endereço, captions, callbacks e botões inline permanece fora da renderização
visual. A camada de cards apenas gera a imagem usada na publicação.

Pontos-chave:

- Fluxos principais preferem Mini App (formulários) para reduzir erros de digitação.
- Publicação de evento no grupo pode ser foto/card com botões inline abaixo.
- Fallback obrigatório: se a renderização/envio da imagem falhar, publica em texto.

## 2. Arquitetura e Tecnologias

- python-telegram-bot (handlers, callbacks, envio/edição de mensagens)
- Starlette + uvicorn (webhook e Mini App HTTP)
- Supabase (PostgreSQL + Storage)
- APScheduler (jobs recorrentes)
- Pillow (renderização de cards)

## 3. Estrutura de Diretórios

```text
assets/
  branding/              # marca d'água opcional do Bode Andarilho
  fonts/                 # fontes .ttf usadas no card padrão
  potencias/             # selos GOB/CMSB/COMAB
  stamps/                # selos de grau (aprendiz/companheiro/mestre)
  templates/             # templates, incluindo o default do sistema
docs/
  supabase_event_cards.sql
  supabase_potencias_normalizadas.sql
src/
  miniapp.py
  render_cards.py        # renderizador de cards com Pillow
  evento_midia.py        # decisão: card especial / template / texto fallback
  sheets_supabase.py
  potencias.py
  ajuda/
main.py
```

## 4. Camada Visual de Eventos

Regra operacional:

1. Se o evento tiver `card_especial_url`, publica o card especial.
2. Senão, se houver template da Loja, renderiza com o template da Loja.
3. Senão, usa o template padrão do sistema.
4. Se qualquer etapa visual falhar, usa texto fallback.

Essa camada não altera:

- callbacks `confirmar|`, `cancelar_card|`, `ver_confirmados|`;
- botões inline do Telegram;
- regras de confirmação/cancelamento;
- link de endereço/Google Maps;
- scheduler/lembretes;
- permissões;
- banco de dados.

## 5. Template Padrão do Sistema

Arquivo:

```text
assets/templates/default_event_card.png
```

Uso:

- sugerido automaticamente quando a Loja não tiver template visual próprio;
- funciona como fallback institucional;
- mantém a comunicação visual mesmo em homologação ou lojas recém-cadastradas.

Montagem visual atual em `src/render_cards.py`:

1. Topo esquerdo: selo da potência em `assets/potencias/` e complemento pequeno.
2. Topo direito: carimbo do grau em `assets/stamps/`.
3. Data/hora centralizadas, com hora em peso visual maior.
4. Linha discreta de grau no corpo.
5. Seção `LOJA`: nome, número destacado, cidade, UF e potência/complemento.
6. Seção `SESSÃO`: tipo de sessão, rito, traje e ágape.
7. Seção `ORDEM DO DIA / OBSERVAÇÕES`: pauta com quebra automática.
8. Rodapé: frase institucional discreta.

Regras visuais consolidadas:

- O texto "Nova Sessão" não é renderizado.
- O rito não aparece no topo.
- O rito aparece apenas dentro da seção `SESSÃO`.
- Links e botões ficam fora da imagem, no Telegram.

## 6. Marca d'água opcional

Arquivo reconhecido:

```text
assets/branding/bode_andarilho_watermark.png
```

Comportamento:

- aplicada somente no template padrão;
- opacidade baixa;
- tratamento em sépia;
- tentativa de remoção de fundo claro;
- posicionamento discreto no centro-direita;
- sem impacto funcional.

Formato recomendado:

- PNG;
- fundo transparente;
- 800x800 a 1200x1200 px;
- estilo gravura/traço;
- sem textos que concorram com os dados da sessão.

## 7. Como editar no futuro

Para trocar apenas o fundo, substitua:

```text
assets/templates/default_event_card.png
```

Para trocar selos sem alterar código:

```text
assets/stamps/aprendiz.png
assets/stamps/companheiro.png
assets/stamps/mestre.png
assets/potencias/gob.png
assets/potencias/cmsb.png
assets/potencias/comab.png
assets/branding/bode_andarilho_watermark.png
```

Para ajustar hierarquia, espaçamentos, fontes, opacidade ou posições, editar
somente o bloco do template padrão em `src/render_cards.py`.

## 8. Potências

Padrão oficial:

- `potencia`: apenas `GOB`, `CMSB` ou `COMAB`
- `potencia_complemento`: texto livre obrigatório para todas

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

Estrutura lógica:

- `lojas/{loja_id}/template.*`
- `eventos/{id_evento}/render.png`
- `eventos/{id_evento}/especial.*`

## 10. Verificação rápida

```bash
python -m compileall main.py src
```

## 11. Referências

- Fluxos atualizados: `docs/fluxos_atualizados_2026_04.md`
- Ajuda/FAQ: `src/ajuda/faq.py`
- Manutenção da base de IA/ajuda: `docs/manutencao_ajuda_e_ia.md`
