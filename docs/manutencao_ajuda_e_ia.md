# Manutencao da Ajuda e Base de IA

Este guia define como manter documentacao e respostas de IA alinhadas ao comportamento real do bot.

## Objetivo

Garantir que:
- a documentacao reflita fluxos atuais;
- a IA responda com base em regras reais do sistema;
- mudancas de fluxo nao gerem respostas desatualizadas.

## Arquivos de referencia

- Documentacao tecnica geral: `docs/documentacao_tecnica.md`
- Fluxos atualizados: `docs/fluxos_atualizados_2026_04.md`
- Base estruturada para IA: `docs/ajuda_ia_base.yaml`
- Conteudo da ajuda no bot: `src/ajuda/*.py`

## Regra operacional

Sempre que houver mudanca de fluxo (callback, permissao, texto oficial, scheduler, onboarding):
1. Atualizar codigo.
2. Atualizar `src/ajuda/*.py` quando houver impacto no usuario.
3. Atualizar `docs/fluxos_atualizados_2026_04.md`.
4. Atualizar `docs/ajuda_ia_base.yaml`.

Sem os 4 passos, a tarefa nao deve ser considerada concluida.

## Checklist rapido por tipo de mudanca

### 1) Novo callback ou novo menu
- Adicionar no fluxo atualizado.
- Criar/ajustar `intent_id` correspondente no YAML.
- Definir `nivel_permitido`, `gatilhos`, `acao_recomendada`.

### 2) Mudanca de texto de regra (ex.: agape, cancelamento, onboarding)
- Atualizar FAQ/guia/tutoriais em `src/ajuda`.
- Atualizar `resposta_oficial` no YAML.

### 3) Mudanca de permissao (nivel 1/2/3)
- Atualizar o YAML na chave `nivel_permitido`.
- Revisar itens de ajuda por nivel.

### 4) Mudanca de scheduler/notificacao
- Atualizar secao de jobs no documento de fluxos.
- Atualizar intents informativas do YAML.

## Regras para respostas de IA

1. IA sugere, bot executa.
2. Sem acao administrativa fora de fluxo oficial.
3. Sem inventar dados de evento, membro ou confirmacao.
4. Em baixa confianca, voltar para menu/fluxo oficial.

## Auditoria segura (IA)

O assistente IA deve registrar apenas metadados operacionais, nunca conteudo sensivel.

Pode registrar:
- tipo de evento (`blocked`, `intent_matched`, `unmatched`, `empty_input`);
- nivel de acesso;
- identificador mascarado do usuario;
- contagem de caracteres/palavras;
- `intent_id` e tipo de acao recomendada.

Nao pode registrar:
- texto bruto da pergunta;
- tokens, secrets, credenciais, querys sensiveis;
- dados pessoais de terceiros.

## Formato recomendado para novas intencoes

```yaml
- intent_id: exemplo_intencao
  nivel_permitido: ["1", "2", "3"]
  gatilhos: ["frase 1", "frase 2"]
  resposta_oficial: "Resposta curta e segura."
  acao_recomendada:
    tipo: callback
    valor: "callback_real_do_bot"
  origem: ["arquivo.py"]
```
