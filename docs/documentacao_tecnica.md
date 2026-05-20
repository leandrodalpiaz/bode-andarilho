# Documentação Técnica - Bode Andarilho Bot

**Versão:** 2.3 (Supabase + Mini App + Cards Visuais + Diploma)
**Última atualização:** 20/05/2026
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
  render_diploma.py      # renderizador do diploma vertical em 2 paginas
  publicidade.py         # helper visual de publicidade do diploma
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

## 7. Diploma digital

Entrada do usuario:

- Menu principal -> `Meu Diploma`
- comando `/perfil`
- callback interno `meu_cadastro`

Fluxo:

1. `src.perfil.mostrar_perfil` busca o cadastro do membro.
2. `src.render_diploma.renderizar_diploma` gera duas imagens PNG 9:16.
3. O Telegram envia as imagens como `send_media_group`.
4. Os botoes de perfil seguem em mensagem separada, pois album do Telegram nao aceita teclado inline anexado.
5. Se a imagem falhar, o perfil textual antigo continua como fallback.

Arquivos base:

```text
assets/branding/diploma_vertical_p1.png
assets/branding/diploma_vertical_p2.png
```

Página 1:

- usa a capa oficial;
- renderiza os dados do perfil (nome, nascimento, grau, loja/número, oriente, potência, VM/MI e nível);
- não inclui blocos de cadastro nem publicidade (a capa é “perfil visual”).

Página 2:

- renderiza o quadro de conquistas a partir de `CONQUISTAS_INFO`;
- progresso 0 fica quase invisível, apenas como silhueta;
- progresso parcial aumenta a opacidade de forma proporcional;
- progresso 100 aparece nítido;
- se a base não tiver dados de conquistas, a imagem ainda renderiza com progresso 0.

### Botões relevantes (painel e grupo)

Painel do obreiro (nível 1):

- `Buscar Sessões`: abre a navegação de sessões e filtros (data/grau/rito/localidade/potência).
- `Minhas Presenças`: lista futuras e histórico; permite cancelar presença no privado.
- `Meu Diploma`: envia carrossel do diploma (2 páginas) e mostra botões de ação (editar/fechar/voltar).
- `Editar Dados`: abre o fluxo de edição do cadastro do próprio usuário.
- `Lembretes`: configura lembretes privados.
- `Organizar`: limpa mensagens antigas do chat privado.
- `Apoiadores`: abre a tela de apoiadores.

Botões do card de evento no grupo:

- `Confirmar presença` (`confirmar|...`): registra presença para o evento.
- `Cancelar presença` (`cancelar_card|...`): remove presença do evento.
- `Ver confirmados` (`ver_confirmados|...`): mostra a lista (temporária no grupo; completa no privado).

Resumo restrito ao secretário:

- `📊 Ver resumo` (`resumo_evento|...`): aparece em telas/DMs do secretário (e admin) e exibe total de confirmados e recortes úteis para ágape/compras. Não deve ser exposto no card público do grupo.

Painel do secretário (nível 2) e fluxos dependentes:

- `Cadastrar evento`: preferencialmente via Mini App; publica o card no grupo e registra os dados no Supabase.
- `Meus eventos`: lista eventos do secretário; permite editar e cancelar.
- `Ver confirmados por evento`: lista confirmados por sessão; consome a tabela `confirmacoes` (com compatibilidade por IDs legados).
- `Gerar Convite Coletivo`: gera token `VOUCHER_...` e link `t.me/.../start=VOUCHER_...` para entrada direta.
- `Configurar notificações`: ativa/desativa alertas privados (ex.: confirmação de presença em evento do secretário).
- `Ver eventos cancelados`: lista sessões canceladas e permite refazer quando previsto.

Painel do administrador (nível 3):

- `Gerenciar todas as sessões`: reaproveita o fluxo de “meus eventos” com visão ampliada.
- `Quadro de Obreiros`: listagem paginada de membros.
- `Atualizar Obreiro`: edição de campos de membros.
- `Promover/Rebaixar secretário`: ajuste de nível e status.
- `Gerenciar lojas`: listagem e operações administrativas sobre lojas.
- `Publicidade/Apoiadores`: governança do programa institucional.
- `Comunicado para Secretários`: envio segmentado (mensagem administrativa) aos secretários.
- `Convite Direto N2`: gera `SEC2_...` vinculado a um `telegram_id` específico (one-time / TTL).

## 8. Publicidade e apoiadores

Publicidade textual:

- `src.apoio.PATROCINADORES` segue como lista estatica/temporaria.
- `src.apoio.obter_texto_patrocinio()` injeta apoio institucional em textos longos.

Publicidade visual do diploma:

- `src.publicidade.obter_publicidade_diploma()` centraliza a configuracao visual.
- Se existir `assets/branding/sponsor_sindoficios.png`, a imagem e usada no rodape da pagina 2.
- Se nao existir, o diploma usa a peca de exemplo: `Sua imagem aqui`.

Gestao administrativa atual:

- Menu principal -> Administracao -> Publicidade/Apoiadores.
- Callback: `admin_publicidade`.
- Acesso restrito a nivel 3.
- A tela mostra a peca ativa, status da imagem e a mensagem usada no diploma.
- Este ciclo nao possui upload/CRUD completo por bot; a troca visual e feita substituindo o asset aprovado.

## 9. Como editar no futuro

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

Para trocar a publicidade visual do diploma, adicione/substitua:

```text
assets/branding/sponsor_sindoficios.png
```

Para ajustar hierarquia, espaçamentos, fontes, opacidade ou posições, editar
somente o bloco do template padrão em `src/render_cards.py`.

Para ajustar o diploma, editar `src/render_diploma.py`.

## 10. Potências

Padrão oficial:

- `potencia`: apenas `GOB`, `CMSB` ou `COMAB`
- `potencia_complemento`: texto livre obrigatório para todas

Exemplos de complemento:

- `GOB-RS`
- `GLMERGS`
- `GORGS`
- `GOSC`
- `GOP`

## 11. Supabase

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

## 12. Verificação rápida

```bash
python -m compileall main.py src
```

Para validar o diploma, gerar preview local em `tmp/diploma_preview_p1.png` e
`tmp/diploma_preview_p2.png` usando `src.render_diploma.renderizar_diploma`.

## 13. Referências

- Fluxos atualizados: `docs/fluxos_atualizados_2026_04.md`
- Ajuda/FAQ: `src/ajuda/faq.py`
- Manutenção da base de IA/ajuda: `docs/manutencao_ajuda_e_ia.md`
