# Fluxos Atualizados do Bode Andarilho (2026-05-12)

Este documento complementa `docs/documentacao_tecnica.md` com os fluxos que estão ativos no código atual e que impactam diretamente navegação, onboarding e suporte com IA.

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

## Diretriz de UX (homologação)

- O fluxo conversacional é secundário.
- Sempre que possível, cadastros e edições devem ocorrer via Mini App (formulários) para reduzir erro de digitação e manter padronização.

## Onboarding grupo -> privado

1. No grupo, o bot responde a palavras de entrada (ex.: `bode`, `menu`, `painel`).
2. Quando possível, direciona o usuário ao privado para operações sensíveis/menus.
3. Quando o privado estiver indisponível, envia fallback no grupo com deep link.

## Mini App (formulários)

O Mini App é usado para:

- cadastro/edição de membro
- cadastro/edição de loja
- cadastro/edição de evento (sessão)

Regras:

- `telegram_id` vem do `initData` validado, não do payload do cliente.
- Campos com padrões (ex.: potência) são validados no backend.

## Cadastro e publicação de evento (sessão)

Fluxo preferencial:

1. Secretário abre o Mini App de cadastro de evento.
2. Preenche dados (a partir da loja vinculada, quando aplicável).
3. O bot gera uma prévia visual no privado (foto + botões).
4. Ao aprovar, o bot salva e publica no grupo com a mesma lógica de callbacks existente.

Fallback:

- Se renderização/envio de foto falhar, o bot publica em texto (o modelo antigo).

## Publicação no grupo (camada visual)

Regra de decisão:

1. `card_especial_url` -> publica card especial
2. template (loja ou default) -> renderiza e publica card
3. caso contrário -> texto fallback

Padrão:

- caption curta (ex.: "Confirme sua presença pelos botões abaixo.")
- botões inline reais do Telegram abaixo da imagem

## Potências (normalização)

Padrão oficial:

- `potencia`: `GOB`, `CMSB`, `COMAB`
- `potencia_complemento`: texto livre obrigatório (ex.: `GOB-RS`, `GLMERGS`, `GORGS`)

O Mini App aplica a regra e o backend valida.

## IA e Ajuda

A camada de IA não executa ações administrativas diretamente.
Ela recomenda fluxos/callbacks oficiais e direciona para o Mini App quando apropriado.

Base:

- `docs/ajuda_ia_base.yaml`
- conteúdo exibido pelo bot: `src/ajuda/*.py`

