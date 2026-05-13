# Manutenção da Ajuda e Base de IA

Este guia define como manter documentação e respostas de IA alinhadas ao comportamento real do bot.

## Objetivo

Garantir que:

- a documentação reflita fluxos atuais;
- a IA responda com base em regras reais do sistema;
- mudanças de fluxo não gerem respostas desatualizadas;
- o Mini App (formulários) seja o caminho preferencial sempre que possível.

## Arquivos de referência

- Documentação técnica geral: `docs/documentacao_tecnica.md`
- Fluxos atualizados: `docs/fluxos_atualizados_2026_04.md`
- Base estruturada para IA: `docs/ajuda_ia_base.yaml`
- Conteúdo de ajuda no bot: `src/ajuda/*.py`

## Regra operacional

Sempre que houver mudança de fluxo (callback, permissão, texto oficial, Mini App, camada visual, scheduler, onboarding):

1. Atualizar código.
2. Atualizar `src/ajuda/*.py` quando houver impacto no usuário.
3. Atualizar `docs/fluxos_atualizados_2026_04.md`.
4. Atualizar `docs/ajuda_ia_base.yaml` (intents/gatilhos/ação recomendada).

Sem os 4 passos, a tarefa não deve ser considerada concluída.

## Checklist rápido por tipo de mudança

### 1) Novo callback ou novo menu

- Adicionar no fluxo atualizado.
- Criar/ajustar `intent_id` correspondente no YAML.
- Definir `nivel_permitido`, `gatilhos`, `acao_recomendada`.

### 2) Mudança de texto de regra (ex.: ágape, cancelamento, potência)

- Atualizar FAQ/guia/tutoriais em `src/ajuda`.
- Atualizar `resposta_oficial` no YAML.

### 3) Mudança de permissão (nível 1/2/3)

- Atualizar o YAML na chave `nivel_permitido`.
- Revisar itens de ajuda por nível.

### 4) Mudança do Mini App (formulários)

- Atualizar o YAML para direcionar ao Mini App sempre que o fluxo conversacional for apenas fallback.
- Garantir que os textos oficiais não incentivem digitação livre quando o formulário já existe.

### 5) Mudança da camada visual (cards)

- Atualizar a documentação técnica (camada visual, assets, migrações).
- Atualizar FAQ/tutoriais se o usuário/secretário perceber alteração na publicação.

## Regras para respostas de IA

1. IA sugere, bot executa.
2. Sem ação administrativa fora de fluxo oficial.
3. Sem inventar dados de evento, membro ou confirmação.
4. Em baixa confiança, voltar para menu/fluxo oficial.
5. Preferir direcionar para o Mini App quando existir formulário correspondente.

## Auditoria segura (IA)

O assistente IA deve registrar apenas metadados operacionais, nunca conteúdo sensível.

Pode registrar:

- tipo de evento (`blocked`, `intent_matched`, `unmatched`, `empty_input`);
- nível de acesso;
- identificador mascarado do usuário;
- contagem de caracteres/palavras;
- `intent_id` e tipo de ação recomendada.

Não pode registrar:

- texto bruto da pergunta;
- tokens, secrets, credenciais, queries sensíveis;
- dados pessoais de terceiros.

## Formato recomendado para novas intenções

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

