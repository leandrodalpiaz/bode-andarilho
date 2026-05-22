# SDD - Ver Confirmados Abaixo Do Card

Projeto: Bode Andarilho
Modulo: eventos e confirmacoes
Arquivo principal: `src/eventos.py`
Data: 22/05/2026
Status: Implementado nesta branch

## Contexto

A lista de confirmados atual esta correta e deve ser preservada. O ajuste de UX trata apenas do local onde essa lista aparece quando o usuario clica em `Ver confirmados` no card de uma sessao.

O comportamento desejado e manter a lista visualmente vinculada ao card de origem, exibindo-a como uma mensagem de reply abaixo do card. Isso preserva a prova social perto da sessao correspondente e evita que o usuario veja uma mensagem solta, desconectada do evento.

## Escopo

Este ajuste nao altera os dados, a formatacao, os botoes, as consultas, as regras de confirmacao/cancelamento nem as integracoes existentes.

Devem ser preservados em `src/eventos.py::ver_confirmados`:

- busca do evento e aliases de identificador;
- consulta das confirmacoes;
- enriquecimento com dados do membro;
- formatacao atual da lista;
- indicacao de visitante;
- botoes ja existentes;
- apoio institucional;
- registro de exibicao de apoio;
- botao `Fechar`;
- envio como mensagem temporaria.

A funcao `ver_confirmados` nao deve ser reescrita por uma versao simplificada. A mudanca e somente de exibicao.

## Comportamento

Ao clicar em `Ver confirmados`, o bot deve enviar a lista atual por `context.bot.send_message(...)`, usando `reply_to_message_id=query.message.message_id` quando houver mensagem de origem no callback.

O card original nao deve ser editado, substituido ou apagado.

A mensagem da lista deve ser temporaria e autoapagada apos 15 segundos, para reduzir poluicao visual no grupo principal.

O botao `Fechar` deve continuar removendo ou ocultando apenas a mensagem da lista, sem tocar no card original.

## Implementacao

Em `src/eventos.py::ver_confirmados`, o envio esperado e:

```python
msg = await context.bot.send_message(
    chat_id=update.effective_chat.id,
    text=texto,
    parse_mode="Markdown",
    reply_markup=reply_markup,
    reply_to_message_id=query.message.message_id if query.message else None,
)
```

Depois do envio, a mensagem da lista deve ser agendada para exclusao automatica em 15 segundos:

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

Os handlers ja estao registrados em `main.py`:

```python
CallbackQueryHandler(ver_confirmados, pattern=r"^ver_confirmados\|")
CallbackQueryHandler(fechar_mensagem, pattern=r"^fechar_mensagem$")
```

## Criterios De Aceite

- Ao clicar em `Ver confirmados` no grupo, a lista aparece abaixo do card como reply encadeado.
- O card original permanece intacto.
- A lista desaparece automaticamente apos 15 segundos.
- Clicar em `Fechar` antes dos 15 segundos remove apenas a lista.
- Nenhum dado, botao, regra ou integracao existente e removido.

## Verificacao

- Conferir que `src/eventos.py::ver_confirmados` continua montando a lista atual.
- Conferir que o envio usa `reply_to_message_id=query.message.message_id`.
- Conferir que `_auto_delete_message(..., delay=15)` e usado para a lista.
- Conferir que os handlers seguem registrados em `main.py`.
- Rodar `python -m compileall src main.py` apos alteracoes de codigo.
