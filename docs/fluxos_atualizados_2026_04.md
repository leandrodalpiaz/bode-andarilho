# Fluxos Atualizados do Bode Andarilho (2026-05-12)

Este documento complementa `docs/documentacao_tecnica.md` com os fluxos que estao ativos no codigo atual e que impactam diretamente navegacao, onboarding e suporte com IA.

## Escopo validado no codigo

Arquivos de maior impacto para fluxo:

- `main.py`
- `src/bot.py`
- `src/miniapp.py`
- `src/cadastro_evento.py`
- `src/eventos.py`
- `src/evento_midia.py`
- `src/render_cards.py`
- `src/sheets_supabase.py`
- `src/potencias.py`
- `src/ajuda/*.py`

## Diretriz de UX (homologacao)

- O fluxo conversacional e secundario.
- Sempre que possivel, cadastros e edicoes devem ocorrer via Mini App (formularios) para reduzir erro de digitacao e manter padronizacao.

## Onboarding grupo -> privado

1. No grupo, o bot responde a palavras de entrada (ex.: `bode`, `menu`, `painel`).
2. Quando possivel, direciona o usuario ao privado para operacoes sensiveis/menus.
3. Quando o privado estiver indisponivel, envia fallback no grupo com deep link.

## Mini App (formularios)

O Mini App e usado para:

- cadastro/edicao de membro
- cadastro/edicao de loja
- cadastro/edicao de evento (sessao)

Regras:

- `telegram_id` vem do `initData` validado, nao do payload do cliente.
- Campos com padroes (ex.: potencia) sao validados no backend.

## Cadastro e publicacao de evento (sessao)

Fluxo preferencial:

1. Secretario abre o Mini App de cadastro de evento.
2. Preenche dados (a partir da loja vinculada, quando aplicavel).
3. O bot gera uma previa visual no privado (foto + botoes).
4. Ao aprovar, o bot salva e publica no grupo com a mesma logica de callbacks existente.

Fallback:

- Se renderizacao/envio de foto falhar, o bot publica em texto (o modelo antigo).

## Publicacao no grupo (camada visual)

Regra de decisao:

1. `card_especial_url` -> publica card especial
2. template (loja ou default) -> renderiza e publica card
3. caso contrario -> texto fallback

Padrao:

- caption curta (ex.: "Confirme sua presenca pelos botoes abaixo.")
- botoes inline reais do Telegram abaixo da imagem

## Potencias (normalizacao)

Padrao oficial:

- `potencia`: `GOB`, `CMSB`, `COMAB`
- `potencia_complemento`: texto livre obrigatorio (ex.: `GOB-RS`, `GLMERGS`, `GORGS`)

O Mini App aplica a regra e o backend valida.

## IA e Ajuda

A camada de IA nao executa acoes administrativas diretamente.
Ela recomenda fluxos/callbacks oficiais e direciona para o Mini App quando apropriado.

Base:

- `docs/ajuda_ia_base.yaml`
- conteudo exibido pelo bot: `src/ajuda/*.py`

