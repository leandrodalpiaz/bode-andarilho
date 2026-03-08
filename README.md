# Documentação do Projeto Bode Andarilho

## Visão Geral
Este projeto é um bot Telegram para gerenciamento de eventos e membros, desenvolvido em Python.

## Otimizações de Performance Aplicadas

### Data das Otimizações: 8 de março de 2026

#### Objetivo
Aplicar otimizações para reduzir a latência de botões de 2-4 segundos para 200-500ms, sem alterações estruturais significativas.

#### Otimizações Implementadas
1. **Otimização de `buscar_membro()`**: Substituído `get_all_records()` por `findall()` com cache TTL de 10 minutos.
2. **Otimização de `buscar_confirmacao()`**: Implementação similar à acima, com cache.
3. **Paralelização em `iniciar_confirmacao_presenca()`**: Uso de `asyncio.gather()` para chamadas simultâneas.
4. **Cache para `_verificar_mensagem_existe()`**: Cache com TTL de 30 segundos.
5. **Otimização de `listar_confirmacoes_por_evento()`**: Uso de `findall()` para filtragem eficiente.
6. **Paginação em `ver_todos_membros()`**: Implementado com 15 itens por página.
7. **Cache LRU em `parse_data_evento()`**: Uso de `functools.lru_cache`.
8. **Timeouts em chamadas Sheets**: Adicionado wrapper com timeout de 2 segundos (pendente).

#### Plano de Reversão
- **Backup Original**: Versões originais preservadas em comentários no código ou via controle de versão Git.
- **Reversão por Função**: Cada otimização é isolada; para reverter, restaurar a versão anterior da função específica.
- **Teste Pré/Pós**: Executar testes locais antes e depois para validação.
- **Em Caso de Problema**: Reverter imediatamente e investigar logs.
- **Exemplo de Reversão para `buscar_membro()`**: Remover cache e retornar ao uso de `get_all_records()` com loop.

### Dependências
Consulte `requirements.txt` para a lista de dependências.

### Execução
Para executar o bot, use `python main.py` ou conforme especificado no `Procfile`.

### Troubleshooting
- Verifique logs para erros relacionados às otimizações.
- Em caso de problemas de performance, considere reverter otimizações conforme o plano acima.