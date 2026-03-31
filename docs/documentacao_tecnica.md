# Documentação Técnica — Bode Andarilho Bot

**Versão:** 2.0 (pós-migração Supabase)
**Última atualização:** 10/03/2026
**Repositório:** `bode_andarilho`
**Runtime:** Python 3.12.0

---

## Sumário

1. [Visão Geral](#1-visão-geral)
2. [Arquitetura e Tecnologias](#2-arquitetura-e-tecnologias)
3. [Estrutura de Diretórios](#3-estrutura-de-diretórios)
4. [Configuração do Ambiente](#4-configuração-do-ambiente)
5. [Estrutura do Banco de Dados](#5-estrutura-do-banco-de-dados)
6. [Sistema de Permissões](#6-sistema-de-permissões)
7. [Handlers e Fluxos de Conversação](#7-handlers-e-fluxos-de-conversação)
8. [Módulo de Navegação (bot.py)](#8-módulo-de-navegação-botpy)
9. [Agendador de Tarefas (scheduler.py)](#9-agendador-de-tarefas-schedulerpy)
10. [Módulo de Ajuda](#10-módulo-de-ajuda)
11. [Manutenção e Monitoramento](#11-manutenção-e-monitoramento)
12. [Fluxo de Dados entre Módulos](#12-fluxo-de-dados-entre-módulos)
13. [Migração Google Sheets → Supabase](#13-migração-google-sheets--supabase)

---

## 1. Visão Geral

O **Bode Andarilho** é um bot do Telegram desenvolvido para gerenciar eventos, presenças e membros de uma comunidade maçônica. O bot opera exclusivamente via webhook (hospedado em Railway) e oferece uma interface de navegação baseada em mensagens editáveis com teclados inline.

**Funcionalidades principais:**

- Cadastro e gerenciamento de membros
- Cadastro e gerenciamento de eventos (secretários)
- Confirmação de presença em eventos
- Sistema de lojas (orientes)
- Perfil do membro com conquistas e nível
- Lembretes automáticos agendados
- Painel administrativo (promoção/rebaixamento de membros)
- Sistema de ajuda com tutoriais, FAQ e glossário

---

## 2. Arquitetura e Tecnologias

### Stack principal

| Componente | Tecnologia |
|---|---|
| Linguagem | Python 3.12.0 |
| Framework do bot | python-telegram-bot 22.6 |
| Servidor web (webhook) | Starlette + uvicorn |
| Banco de Dados | **Supabase (PostgreSQL)** |
| Agendador | APScheduler 3.11.2 |
| Hospedagem | Railway |

Os dados são persistidos no **Supabase (PostgreSQL)** através do cliente oficial `supabase-py`.

### Diagrama de arquitetura

```
┌─────────────┐     HTTPS/webhook      ┌──────────────────────┐
│  Telegram   │ ─────────────────────► │  Railway (uvicorn)   │
│  Servers    │                         │  main.py             │
└─────────────┘                         └──────────┬───────────┘
                                                    │
                                         ┌──────────▼───────────┐
                                         │  Handlers             │
                                         │  (bot.py, cadastro,   │
                                         │  eventos, perfil...)  │
                                         └──────────┬────────────┘
                                                    │
                                         ┌──────────▼───────────┐
                                         │  sheets_supabase.py   │
                                         │  (camada de dados)    │
                                         └──────────┬────────────┘
                                                    │
                                         ┌──────────▼───────────┐
                                         │  Supabase            │
                                         │  (PostgreSQL)        │
                                         │  membros / eventos / │
                                         │  confirmacoes / lojas│
                                         └──────────────────────┘
```

### Diagrama de fluxo de requisição

```
Telegram → Webhook (Railway) → main.py → Handlers → sheets_supabase.py → Supabase (PostgreSQL)
```

### Processo de inicialização (`main.py`)

1. Valida `TELEGRAM_TOKEN` e `RENDER_EXTERNAL_URL`
2. Constrói o `telegram.ext.Application`
3. Registra todos os handlers (`register_handlers`)
4. Inicializa e inicia a aplicação
5. Remove e reconfigura o webhook do Telegram
6. Cria a app Starlette com rotas: `GET /`, `GET /health`, `POST {WEBHOOK_PATH}`
7. Inicia o `uvicorn.Server` na porta configurada
8. Chama `iniciar_scheduler(telegram_app)` para os jobs APScheduler
9. Registra handlers de sinal `SIGTERM`/`SIGINT` para shutdown gracioso

---

## 3. Estrutura de Diretórios

```
bode_andarilho/
├── main.py                    # Ponto de entrada, webhook, registro de handlers
├── Procfile                   # web: python main.py
├── requirements.txt           # Dependências Python
├── runtime.txt                # python-3.12.0
├── docs/
│   └── documentacao_tecnica.md  # Este arquivo
└── src/
    ├── bot.py                 # Gerenciador de navegação, menu principal, botao_handler
    ├── cadastro.py            # Fluxo de cadastro de novos membros
    ├── cadastro_evento.py     # Fluxo de cadastro de eventos (secretário)
    ├── editar_perfil.py       # Fluxo de edição do perfil
    ├── eventos.py             # Listagem e confirmação de presença (membro)
    ├── eventos_secretario.py  # Painel do secretário (gerenciar eventos)
    ├── lembretes.py           # Funções de envio de lembretes agendados
    ├── lojas.py               # Gerenciamento de lojas (secretário)
    ├── messages.py            # Textos e templates de mensagens
    ├── perfil.py              # Exibição de perfil, conquistas, marcos
    ├── permissoes.py          # Sistema de níveis de acesso
    ├── scheduler.py           # Inicialização e jobs do APScheduler

    ├── sheets_supabase.py     # Módulo ativo - acesso ao Supabase (PostgreSQL)
    ├── admin_acoes.py         # Painel admin (promover/rebaixar/editar membros)
    └── ajuda/
        ├── __init__.py
        ├── conquistas.py      # Sistema de conquistas e marcos
        ├── dicas.py           # Seção de dicas
        ├── faq.py             # Perguntas frequentes
        ├── glossario.py       # Glossário maçônico
        ├── menus.py           # Menus e roteamento da seção de ajuda
        ├── nivel1.py          # Conteúdo nível iniciado
        ├── nivel2.py          # Conteúdo nível companheiro
        ├── nivel3.py          # Conteúdo nível mestre
        ├── sobre.py           # Sobre o bot
        └── tutoriais.py       # Tutoriais de uso
```

---

## 4. Configuração do Ambiente

### 4.1 Variáveis de Ambiente

As seguintes variáveis de ambiente devem ser definidas (em produção, configuradas no painel do Railway):

```env
# Telegram
TELEGRAM_TOKEN=<token do bot obtido no BotFather>
TELEGRAM_WEBHOOK_SECRET=<segredo aleatório forte para validar chamadas do webhook>

# Render
RENDER_EXTERNAL_URL=https://worker-production-2d2d.up.railway.app
PORT=10000
WEBHOOK_PATH=/telegram/webhook

# Grupos
GRUPO_PRINCIPAL_ID=<ID numérico do grupo principal do Telegram>

# Supabase
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sb_secret_sua_chave_aqui
```

> **Nota:** A variável `GOOGLE_CREDENTIALS` não é mais necessária e pode ser removida com segurança.

### 4.2 requirements.txt

```
# Core
python-telegram-bot==22.6
APScheduler==3.11.2
requests==2.32.5

# Webhook (Railway)
starlette==0.37.0
uvicorn==0.30.0
httpx==0.28.1

# Supabase
supabase==2.28.0
websockets==15.0.1

# Dependências indiretas
certifi==2026.1.4
charset-normalizer==3.4.4
idna==3.11
urllib3==2.6.3
pyasn1==0.6.2
pyasn1_modules==0.4.2
rsa==4.9.1
cffi==2.0.0
cryptography==46.0.5
pycparser==3.0
typing_extensions==4.15.0
tzdata==2025.3
tzlocal==5.3.1
h11==0.16.0
httpcore==1.0.9
anyio==4.12.1
python-dotenv==1.2.1
```

### 4.3 Configuração local (.env)

Para desenvolvimento local, crie um arquivo `.env` na raiz do projeto:

```env
TELEGRAM_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
RENDER_EXTERNAL_URL=https://worker-production-2d2d.up.railway.app
PORT=10000
WEBHOOK_PATH=/telegram/webhook
GRUPO_PRINCIPAL_ID=...
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sb_secret_sua_chave_aqui
```

---

## 5. Estrutura do Banco de Dados (Supabase)

O banco de dados utiliza **Supabase (PostgreSQL)** com 5 tabelas:

### 5.1 Tabela `membros`

| Coluna (Sheets) | Coluna (DB) | Tipo | Descrição |
|---|---|---|---|
| Telegram ID | `telegram_id` | BIGINT (PK) | ID único do usuário no Telegram |
| Nome | `nome` | TEXT | Nome completo do membro |
| Grau | `grau` | TEXT | Grau maçônico atual |
| Loja | `loja` | TEXT | Nome da loja do membro |
| Oriente | `oriente` | TEXT | Cidade/oriente da loja |
| Potência | `potencia` | TEXT | Potência maçônica |
| Nivel | `nivel` | TEXT | Nível de acesso no bot (`"1"`, `"2"` ou `"3"`) |
| Notificações | `notificacoes` | TEXT | `"SIM"` ou `"NÃO"` |
| Data Cadastro | `data_cadastro` | TEXT | Data/hora do cadastro |

**Índice:** `telegram_id` (PRIMARY KEY)

### 5.2 Tabela `eventos`

| Coluna (Sheets) | Coluna (DB) | Tipo | Descrição |
|---|---|---|---|
| ID Evento | `id_evento` | TEXT (PK) | Identificador único (UUID hex 32 chars) |
| Nome Loja | `nome_loja` | TEXT | Nome da loja anfitriã |
| Oriente | `oriente` | TEXT | Cidade do evento |
| Tipo Evento | `tipo_evento` | TEXT | Tipo (sessão, fraternização, etc.) |
| Data Evento | `data_evento` | TEXT | Data no formato DD/MM/AAAA |
| Hora Evento | `hora_evento` | TEXT | Hora no formato HH:MM |
| Grau | `grau` | TEXT | Grau mínimo para participação |
| Potência | `potencia` | TEXT | Potência do evento |
| Status | `status` | TEXT | `"ativo"` ou `"cancelado"` |
| Secretario Telegram ID | `secretario_telegram_id` | BIGINT | ID do secretário responsável |
| Data Criacao | `data_criacao` | TEXT | Data/hora de criação |

**Índices:** `status`, `secretario_telegram_id`

### 5.3 Tabela `confirmacoes`

| Coluna (Sheets) | Coluna (DB) | Tipo | Descrição |
|---|---|---|---|
| ID Confirmação | `id` | SERIAL (PK) | ID auto-incremento |
| ID Evento | `id_evento` | TEXT | FK → `eventos.id_evento` |
| Telegram ID | `telegram_id` | BIGINT | FK → `membros.telegram_id` |
| Nome | `nome` | TEXT | Nome do membro na confirmação |
| Data Confirmacao | `data_confirmacao` | TEXT | Data/hora da confirmação |

**Índices:** `id_evento`, `telegram_id`

### 5.4 Tabela `lojas`

| Coluna (Sheets) | Coluna (DB) | Tipo | Descrição |
|---|---|---|---|
| Telegram ID | `telegram_id` | BIGINT | ID do secretário dono da loja |
| Nome Loja | `nome_loja` | TEXT | Nome da loja |
| Número | `numero` | TEXT | Número da loja |
| Rito | `rito` | TEXT | Rito praticado |
| Oriente da Loja | `oriente_da_loja` | TEXT | Cidade/oriente da loja |
| Potência | `potencia` | TEXT | Potência da loja |

**Índice:** `telegram_id`

### 5.5 Observações sobre o schema

### 5.6 Tabela `notificacoes_secretario_pendentes`

| Coluna (DB) | Tipo | Descrição |
|---|---|---|
| id | BIGSERIAL (PK) | Identificador da pendência |
| secretario_id | BIGINT | Telegram ID do secretário |
| nome | TEXT | Nome do irmão que confirmou |
| data_sessao | TEXT | Data da sessão |
| loja | TEXT | Loja da sessão |
| agape | TEXT | Opção de participação no ágape |
| criado_em | TIMESTAMPTZ | Data/hora de criação da pendência |

Essa tabela é usada para consolidar notificações de confirmação durante a janela de silêncio (22:00–07:00), com envio em lote fora da janela.

Os nomes das colunas no banco seguem o padrão `snake_case` sem acentos (ex: `telegram_id`, `nome_loja`, `potencia`). O módulo `sheets_supabase.py` realiza o mapeamento bidirecional automaticamente, expondo os dados com os nomes originais para todos os outros módulos do sistema, garantindo compatibilidade sem necessidade de alterações no restante do código.

---

## 6. Sistema de Permissões

Definido em `src/permissoes.py`. Três níveis de acesso controlam quais funcionalidades estão disponíveis para cada usuário.

| Nível | Label | Capacidades |
|---|---|---|
| `"1"` | Comum (membro) | Visualizar eventos, confirmar presença, ver perfil próprio |
| `"2"` | Secretário | Nível 1 + cadastrar/gerenciar próprios eventos, gerenciar lojas |
| `"3"` | Admin | Níveis 1+2 + promover/rebaixar membros, editar qualquer membro |

**Função pública:**

```python
get_nivel(user_id: int) -> str
```

Consulta o banco de dados e retorna o nível do membro. Retorna `"1"` se o membro não for encontrado. O resultado é sempre uma string limpa. Utilizada em `botao_handler`, `menu_principal_teclado` e todos os painéis de secretário/admin.

---

## 7. Handlers e Fluxos de Conversação

Registrados em `main.py` via `register_handlers(app)`. A ordem de registro é crítica para evitar conflitos.

### 7.1 ConversationHandlers (prioridade máxima)

| Handler | Módulo | Descrição |
|---|---|---|
| `cadastro_handler` | `cadastro.py` | Fluxo de cadastro de novos membros |
| `confirmacao_presenca_handler` | `eventos.py` | Confirmação de presença em eventos |
| `cadastro_evento_handler` | `cadastro_evento.py` | Cadastro de eventos (secretário) |
| `promover_handler` | `admin_acoes.py` | Promoção de membro para secretário/admin |
| `rebaixar_handler` | `admin_acoes.py` | Rebaixamento de membro |
| `editar_membro_handler` | `admin_acoes.py` | Edição de dados de qualquer membro (admin) |
| `editar_perfil_handler` | `editar_perfil.py` | Edição do próprio perfil |
| `editar_evento_secretario_handler` | `eventos_secretario.py` | Edição de eventos do secretário |
| `cadastro_loja_handler` | `lojas.py` | Cadastro de lojas (secretário) |

### 7.2 CommandHandlers

| Comando | Handler | Descrição |
|---|---|---|
| `/start` | `start` (bot.py) | Inicia o bot; verifica cadastro |
| `/ping` | inline | Verifica se o bot está online |

### 7.3 CallbackQueryHandlers (por área funcional)

| Padrão | Área |
|---|---|
| Ajuda (via `src.ajuda.menus`) | Sistema de ajuda |
| `^mostrar_marcos_secretario$`, `^mostrar_conquistas_membro$` | Perfil/conquistas |
| `^(ver_eventos\|mostrar_eventos\|eventos\|voltar_eventos)$` | Eventos |
| `^data\|`, `^grau\|`, `^evento\|`, `^calendario\|`, `^calendario_atual$` | Filtros de eventos |
| `^minhas_confirmacoes.*$`, `^detalhes_confirmado\|`, `^detalhes_historico\|` | Confirmações do membro |
| `^ver_confirmados\|`, `^confirma_cancelar\|`, `^cancelar\|`, `^fechar_mensagem$` | Gerência de confirmações |
| `^meus_eventos$`, `^ver_confirmados_secretario$`, `^visualizar_confirmados\|`, etc. | Painel do secretário |
| `^admin_ver_membros$`, `^membros_page_.*$`, `^menu_notificacoes$`, etc. | Painel admin |
| `^menu_lojas$`, `^loja_listar$`, `^loja_excluir_menu$`, `^excluir_loja_\d+$`, etc. | Lojas |
| `.*` (catch-all) | `botao_handler` (bot.py) |

### 7.4 Outros handlers

| Handler | Tipo | Descrição |
|---|---|---|
| `novo_membro_grupo_handler` | `ChatMemberHandler` | Boas-vindas a novos membros no grupo |
| `bode_grupo_handler` | `MessageHandler` | Responde à palavra "bode" no grupo |
| `mensagem_grupo_handler` | `MessageHandler` | Redireciona `/start` e `/cadastro` do grupo para o privado |

### 7.5 Endpoints web

| Rota | Método | Resposta |
|---|---|---|
| `/` | GET | `"Bode Andarilho Bot - Online"` |
| `/health` | GET | `"OK"` |
| `{WEBHOOK_PATH}` | POST | Processa update do Telegram |

---

## 8. Módulo de Navegação (bot.py)

O `bot.py` implementa uma navegação baseada em **3 mensagens fixas** por usuário, editadas in-place:

| Tipo | Constante | Papel |
|---|---|---|
| Menu | `TIPO_MENU` | Botões do menu principal (fixo) |
| Contexto | `TIPO_CONTEXTO` | Breadcrumb / indicador de localização |
| Resultado | `TIPO_RESULTADO` | Conteúdo principal da tela atual |

### Funções públicas principais

| Função | Descrição |
|---|---|
| `menu_principal_teclado(nivel)` | Gera o teclado inline do menu; exibe painéis de secretário/admin para níveis 2/3 |
| `criar_estrutura_inicial(context, user_id, membro)` | Envia as 3 mensagens iniciais |
| `navegar_para(update, context, caminho, conteudo, teclado, limpar_conteudo)` | Atualiza breadcrumb + resultado |
| `voltar_ao_menu_principal(update, context)` | Reseta contexto e resultado ao estado inicial |
| `limpar_historico(update, context)` | Tenta apagar até 100 mensagens anteriores no chat |
| `start(update, context)` | Handler `/start`: verifica cadastro → exibe menu ou inicia cadastro |
| `botao_handler(update, context)` | Catch-all: roteia callbacks conhecidos; aplica verificação de permissões |

### Cache de estado

- `estado_mensagens: Dict[int, dict]` — Rastreia `{user_id: {tipo: {message_id, content_hash}}}` para edição in-place
- Verificação de existência de mensagem: TTL de 30 segundos

---

## 9. Agendador de Tarefas (scheduler.py)

Utiliza `APScheduler` com backend `AsyncIOScheduler`.

| Job ID | Gatilho | Horário | Função chamada |
|---|---|---|---|
| `job_lembretes_24h` | `cron` | Todo dia 08:00 | `enviar_lembretes_24h(bot)` |
| `job_lembretes_meio_dia` | `cron` | Todo dia 12:00 | `enviar_lembretes_meio_dia(bot)` |
| `job_celebracao_mensal` | `cron` | Dia 1 de cada mês, 09:00 | `enviar_celebracao_mensal(bot)` |

A função `iniciar_scheduler(app)` é idempotente — não recria o scheduler se já estiver rodando.

---

## 10. Módulo de Ajuda

Localizado em `src/ajuda/`. Contém conteúdo educativo e de suporte ao usuário, organizado em submódulos:

| Arquivo | Conteúdo |
|---|---|
| `menus.py` | Roteamento e menus da área de ajuda |
| `conquistas.py` | Sistema de conquistas e marcos do membro |
| `dicas.py` | Dicas de uso do bot |
| `faq.py` | Perguntas frequentes |
| `glossario.py` | Glossário de termos maçônicos |
| `nivel1.py` | Conteúdo para grau de iniciado |
| `nivel2.py` | Conteúdo para grau de companheiro |
| `nivel3.py` | Conteúdo para grau de mestre |
| `sobre.py` | Informações sobre o bot |
| `tutoriais.py` | Tutoriais passo a passo |

---

## 11. Manutenção e Monitoramento

### 11.1 Logs

O bot utiliza o sistema de logging padrão do Python. Em produção (Railway), os logs são visualizados pelo painel do serviço em tempo real. Eventos críticos como falha de webhook, erros no scheduler e exceções nos handlers são registrados automaticamente pelo `python-telegram-bot`.

### 11.2 Pontos de Atenção

- **Banco de dados:** Não alterar os nomes das colunas no Supabase manualmente sem atualizar o mapeamento em `sheets_supabase.py`
- **Webhook:** O bot deleta e recria o webhook a cada restart. Em caso de conflito, usar `deleteWebhook` manualmente via API do Telegram.
- **Scheduler:** O APScheduler roda na mesma thread assíncrona do bot. Não inicializar manualmente fora de `iniciar_scheduler`.
- **Backup:** O Supabase realiza backups automáticos diários. Backups manuais podem ser feitos via **SQL Editor > Export** ou pela API de administração.
- **Cache:** `sheets_supabase.py` mantém cache em memória (TTL 10min para membros, 5min para confirmações). Reiniciar o processo invalida todo o cache.

### 11.3 Recriação do Zero

Para recriar o ambiente completo do zero:

1. Criar conta/projeto no Railway
2. Conectar ao repositório no GitHub
3. Configurar todas as variáveis de ambiente (seção 4.1)
4. Definir o processo como `web: python main.py` (Procfile)
5. Criar o projeto no Supabase e executar o SQL de criação das tabelas (incluindo `docs/supabase_notificacoes_secretario.sql` para pendências do secretário)
6. Migrar os dados existentes executando os INSERTs de seed disponíveis em `docs/supabase_seed.sql`
7. Criar um bot no BotFather e adicionar ao grupo principal como administrador
8. Fazer deploy; o bot configurará o webhook automaticamente ao iniciar

---

## 12. Fluxo de Dados entre Módulos

```
┌─────────────────────────────────────────────────────────┐
│                     main.py                              │
│  (inicialização, webhook, register_handlers)             │
└────────────────────────┬────────────────────────────────┘
                         │ importa e registra
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌──────────────┐  ┌─────────────┐  ┌───────────────┐
│   bot.py     │  │  scheduler  │  │  handlers     │
│  (navegação) │  │  .py        │  │  (cadastro,   │
│              │  │             │  │  eventos,     │
│              │  │             │  │  perfil, etc) │
└──────┬───────┘  └──────┬──────┘  └───────┬───────┘
       │                 │                  │
       └─────────────────┴──────────────────┘
                         │
                         │ chamam funções de dados
                         ▼
         ┌─────────────────────┐
         │  sheets_supabase.py  │
         │  (Supabase Client)   │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Supabase            │
         │  (PostgreSQL)        │
         │  membros / eventos / │
         │  confirmacoes / lojas│
         └─────────────────────┘
```

### Fluxo de uma requisição típica (ex: confirmar presença)

```
Telegram (usuário clica botão)
    │
    ▼ POST {WEBHOOK_PATH}
main.py (Starlette recebe, passa ao Application)
    │
    ▼
confirmacao_presenca_handler (ConversationHandler em eventos.py)
    │
    ├── buscar_membro(telegram_id)      ─►  sheets_supabase.py  ─►  Supabase
    ├── listar_eventos()                ─►  sheets_supabase.py  ─►  Supabase
    ├── registrar_confirmacao(dados)    ─►  sheets_supabase.py  ─►  Supabase
    │
    ▼
navegar_para(update, context, ...)  ─►  bot.py  ─►  Telegram API (edit message)
```

---

## 13. Migração Google Sheets → Supabase

**Data da migração:** 10/03/2026

**Motivação:** O Google Sheets apresenta limitações de performance, quotas de API e concorrência que podem impactar o crescimento do bot. O Supabase oferece um banco de dados PostgreSQL gerenciado, com performance superior, suporte a índices, consultas SQL nativas e uma API REST automática.

---

### O que mudou

O módulo `sheets.py` foi substituído pelo `sheets_supabase.py`. Todas as assinaturas de função foram mantidas idênticas para garantir compatibilidade total com os demais módulos. A troca foi feita apenas nos imports de cada arquivo.

---

### Mapeamento de nomenclatura

Os campos no banco seguem `snake_case` sem acentos. O módulo `sheets_supabase.py` realiza a conversão automaticamente em ambas as direções, mantendo transparência total para o restante do sistema.

Exemplos:

| Nome original (Sheets) | Coluna no banco (PostgreSQL) |
|---|---|
| `Telegram ID` | `telegram_id` |
| `Nome` | `nome` |
| `Potência` | `potencia` |
| `Notificações` | `notificacoes` |
| `Oriente da Loja` | `oriente_da_loja` |
| `Secretario Telegram ID` | `secretario_telegram_id` |
| `ID Evento` | `id_evento` |
| `Data Evento` | `data_evento` |

---

### Índices criados para performance

- `membros`: `telegram_id` (PRIMARY KEY)
- `eventos`: `status`, `secretario_telegram_id`
- `confirmacoes`: `id_evento`, `telegram_id`
- `lojas`: `telegram_id`

---

### Cache em memória (`sheets_supabase.py`)

Para reduzir chamadas ao banco, o módulo mantém cache em memória:

| Cache | TTL | Escopo |
|---|---|---|
| `_cache_membros` | 600s (10 min) | Por `telegram_id` |
| `_cache_confirmacoes` | 300s (5 min) | Por `(id_evento, telegram_id)` |

Operações de escrita (`atualizar_membro`, `cancelar_confirmacao`, etc.) invalidam as entradas relevantes automaticamente.

---

### Arquivos alterados na migração

Os seguintes módulos tiveram apenas seus imports atualizados (de `sheets` para `sheets_supabase`):

`bot.py`, `cadastro.py`, `cadastro_evento.py`, `editar_perfil.py`, `eventos.py`,
`eventos_secretario.py`, `lembretes.py`, `lojas.py`, `perfil.py`, `permissoes.py`,
`admin_acoes.py`, `conquistas.py`, `main.py`

**Total: 13 módulos alterados**

**Arquivo adicionado:** `src/sheets_supabase.py`

**Arquivo removido (legado):** `src/sheets.py` — removido após confirmação de que nenhum módulo o importava

---

### Variáveis de ambiente alteradas

| Variável | Status |
|---|---|
| `GOOGLE_CREDENTIALS` | Removida (não mais necessária) |
| `SUPABASE_URL` | Adicionada |
| `SUPABASE_KEY` | Adicionada |
| `TELEGRAM_TOKEN` | Sem alteração |
| `RENDER_EXTERNAL_URL` | Sem alteração |
| `PORT` | Sem alteração |
| `WEBHOOK_PATH` | Sem alteração |
| `GRUPO_PRINCIPAL_ID` | Sem alteração |

---

### Dependências alteradas no requirements.txt

**Removidas:**
```
gspread==6.0.0
oauth2client==4.1.3
google-auth==2.23.4
```

**Adicionadas:**
```
supabase==2.28.0
websockets==15.0.1
```
