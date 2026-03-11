# Roteiro de Teste - Producao Livre (Pre-Oficial)

Objetivo: validar comportamento real de uso com secretarios reais e eventos reais, mantendo ambiente ainda em fase de teste.

## 1. Preparacao do ambiente

1. Definir variaveis no servico:
- `WEBHOOK_MAX_CONNECTIONS=20` (inicial)
- `DROP_PENDING_UPDATES_ON_BOOT=false`

2. Confirmar webhook ativo e sem fila crescente:
- Verificar logs de inicializacao.
- Confirmar URL de webhook correta.

3. Confirmar base com IDs validos:
```sql
select count(*) as sem_id_evento
from public.eventos
where id_evento is null or btrim(id_evento) = '';
```
Esperado: `0`.

## 2. Massa de teste controlada

1. Cadastrar 2 a 4 secretarios reais.
2. Cada secretario cadastra 2 a 3 eventos.
3. Cadastrar 15 a 30 membros reais (ou misto real + teste).
4. Distribuir confirmacoes entre eventos:
- 30% com agape
- 70% sem agape

## 3. Testes funcionais obrigatorios

### 3.1 Fluxo de cadastro e menu
1. Novo membro faz cadastro completo no privado.
2. Validar retorno ao menu principal.
3. Validar botoes principais funcionando apos /start.

### 3.2 Fluxo de evento
1. Secretario cadastra evento e publica no grupo.
2. Validar mensagem com botoes de confirmacao.
3. Validar detalhes do evento no privado.

### 3.3 Fluxo de confirmacao
1. Membro confirma presenca no grupo.
2. Validar feedback imediato no callback.
3. Validar mensagem no privado com resumo.
4. Validar tentativa de segunda confirmacao (deve informar que ja confirmou).

### 3.4 Fluxo de cancelamento
1. Membro cancela presenca.
2. Validar remocao da confirmacao.
3. Reconfirmar e validar retorno ao estado correto.

### 3.5 Fluxo de secretaria
1. Abrir "Meus eventos".
2. Abrir "Ver confirmados".
3. Validar resumo com total, com agape, sem agape.
4. Validar "Copiar lista".

### 3.6 Lembretes e notificacoes
1. Ativar notificacoes para secretario.
2. Gerar novas confirmacoes.
3. Validar entrega de notificacao.
4. Validar comportamento no horario silencioso (22h-07h):
- nao enviar imediato
- consolidar no flush programado

## 4. Teste de concorrencia (pico realista)

Objetivo: reproduzir "horario de grupo" com varias interacoes curtas.

1. Janela de 10 minutos.
2. 10 a 20 usuarios acionam ao mesmo tempo:
- `ver_eventos`
- abrir detalhes
- confirmar/cancelar
3. Coletar evidencias:
- tempo medio de resposta percebido
- callbacks expirados
- erros de Supabase

Meta inicial:
- resposta visual de callback em ate 1.5s
- sem erros criticos em log

## 5. Queries de auditoria rapida

### 5.1 Confirmacoes orfas
```sql
select count(*) as confirmacoes_orfas
from public.confirmacoes c
left join public.eventos e on e.id_evento = c.id_evento
where e.id_evento is null;
```
Esperado: `0`.

### 5.2 Eventos sem secretario valido
```sql
select count(*) as eventos_sem_secretario
from public.eventos
where secretario_telegram_id is null or btrim(secretario_telegram_id::text) = '';
```
Esperado: `0` para novos eventos reais.

### 5.3 Duplicidade de confirmacao por usuario/evento
```sql
select id_evento, telegram_id, count(*) as qtd
from public.confirmacoes
group by id_evento, telegram_id
having count(*) > 1;
```
Esperado: sem linhas.

## 6. Criterios de aprovacao para ir a producao oficial

1. 3 dias consecutivos sem erro critico.
2. Nenhum botao principal quebrado.
3. Sem crescimento anormal de latencia em horario de pico.
4. Confirmacoes e cancelamentos consistentes na base.
5. Lembretes entregues sem falha sistamica.

## 7. Plano de acao se aparecer problema

1. Problema de callback lento:
- reduzir operacoes sincronas no handler afetado
- aumentar `WEBHOOK_MAX_CONNECTIONS` para 30

2. Problema de notificacao:
- validar `secretario_telegram_id`
- validar tabela `notificacoes_secretario_pendentes`

3. Problema de consistencia:
- executar queries de auditoria
- corrigir dados e repetir teste do fluxo especifico

## 8. Registro diario recomendado

Preencher ao final de cada dia:
- Data
- Numero de usuarios ativos
- Numero de eventos criados
- Numero de confirmacoes
- Tempo medio percebido de resposta
- Erros encontrados
- Status: Aprovado / Requer ajuste
