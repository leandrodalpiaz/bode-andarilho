# SDD - Ver Confirmados Abaixo Do Card

Projeto: Bode Andarilho
Módulo: eventos e confirmações
Arquivo principal: `src/eventos.py`
Data: 22/05/2026
Status: Implementado nesta branch

## Contexto

A lista de confirmados atual está correta e deve ser preservada. O ajuste de UX trata apenas do local onde essa lista aparece quando o usuário clica em `Ver confirmados` no card de uma sessão.

O comportamento desejado é manter a lista visualmente vinculada ao card de origem, exibindo-a como uma mensagem de reply abaixo do card. Isso preserva a prova social perto da sessão correspondente e evita que o usuário veja uma mensagem solta, desconectada do evento.

## Escopo

Este ajuste não altera os dados, a formatação, os botões, as consultas, as regras de confirmação/cancelamento nem as integrações existentes.

Devem ser preservados em `src/eventos.py::ver_confirmados`:

- busca do evento e aliases de identificador;
- consulta das confirmações;
- enriquecimento com dados do membro;
- formatação atual da lista;
- indicação de visitante;
- botões já existentes;
- apoio institucional;
- registro de exibição de apoio;
- botão `Fechar`;
- envio como mensagem temporária.

A função `ver_confirmados` não deve ser reescrita por uma versão simplificada. A mudança é somente de exibição.

## Comportamento

Ao clicar em `Ver confirmados`, o bot deve enviar a lista atual por `context.bot.send_message(...)`, usando `ReplyParameters(message_id=query.message.message_id)` quando houver mensagem de origem no callback.

O card original não deve ser editado, substituído ou apagado.

A mensagem da lista deve ser temporária e autoapagada após 15 segundos, para reduzir poluição visual no grupo principal.

O botão `Fechar` deve continuar removendo ou ocultando apenas a mensagem da lista, sem tocar no card original.

## Implementação

Em `src/eventos.py::ver_confirmados`, o envio esperado é:

```python
reply_parameters = (
    ReplyParameters(message_id=query.message.message_id)
    if query.message
    else None
)

msg = await context.bot.send_message(
    chat_id=update.effective_chat.id,
    text=texto,
    parse_mode="Markdown",
    reply_markup=reply_markup,
    reply_parameters=reply_parameters,
)
```

Depois do envio, a mensagem da lista deve ser agendada para exclusão automática em 15 segundos:

```python
asyncio.create_task(
    _auto_delete_message(
        context,
        update.effective_chat.id,
        msg.message_id,
        delay=15,
    )
)
```

Os handlers já estão registrados em `main.py`:

```python
CallbackQueryHandler(ver_confirmados, pattern=r"^ver_confirmados\|")
CallbackQueryHandler(fechar_mensagem, pattern=r"^fechar_mensagem$")
```

## Critérios de Aceite

- Ao clicar em `Ver confirmados` no grupo, a lista aparece abaixo do card como reply encadeado.
- O card original permanece intacto.
- A lista desaparece automaticamente após 15 segundos.
- Clicar em `Fechar` antes dos 15 segundos remove apenas a lista.
- Nenhum dado, botão, regra ou integração existente é removido.

## Verificação

- Conferir que `src/eventos.py::ver_confirmados` continua montando a lista atual.
- Conferir que o envio usa `ReplyParameters(message_id=query.message.message_id)`.
- Conferir que `_auto_delete_message(..., delay=15)` é usado para a lista.
- Conferir que os handlers seguem registrados em `main.py`.
- Rodar `python -m compileall src main.py` após alterações de código.
