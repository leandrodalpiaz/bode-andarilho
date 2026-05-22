import re

with open(r"src\miniapp.py", "r", encoding="utf-8") as f:
    content = f.read()

validar_loja_code = """
def _validar_loja_para_evento(dados: dict) -> str | None:
    faltantes = []
    campos = [
        ("nome_loja", "nome da loja"),
        ("numero_loja", "número da loja"),
        ("oriente", "oriente/cidade"),
        ("rito", "rito"),
        ("potencia", "potência principal"),
        ("potencia_complemento", "potência local"),
        ("endereco", "endereço da sessão"),
    ]
    for chave, rotulo in campos:
        valor = str(dados.get(chave) or "").strip()
        if chave == "numero_loja" and valor == "0":
            valor = ""
        if not valor:
            faltantes.append(rotulo)
    if faltantes:
        return f"A loja selecionada está com o cadastro incompleto. Por favor, edite a loja e preencha os seguintes campos antes de criar uma sessão: {', '.join(faltantes)}."
    return None

"""

if "def _validar_loja_para_evento" not in content:
    # insert before _validar_dados_evento
    content = content.replace("def _validar_dados_evento(", validar_loja_code + "def _validar_dados_evento(")

if "_validar_loja_para_evento(dados)" not in content:
    content = content.replace(
        "    dados = _aplicar_loja_cadastrada_ao_evento(dados, lojas_existentes)\n    mensagem = _validar_dados_evento(dados)",
        "    dados = _aplicar_loja_cadastrada_ao_evento(dados, lojas_existentes)\n    mensagem_loja = _validar_loja_para_evento(dados)\n    if mensagem_loja:\n        return _json_error(mensagem_loja, 400)\n    mensagem = _validar_dados_evento(dados)"
    )

# Now fix api_cadastro_evento
# Look for the try block that sends the group message
api_cadastro_pattern = re.compile(
    r'    try:\n        grupo_id_int = int\(_GRUPO_PRINCIPAL_ID\)\n        await bot\.send_message\(\n            chat_id=grupo_id_int,\n            text=texto_grupo,\n            parse_mode="Markdown",\n            reply_markup=_teclado_pos_publicacao\(id_evento, agape\),\n        \)\n    except Exception as eg:\n        logger\.warning\("Falha ao publicar evento no grupo: %s", eg\)\n\n    await bot\.send_message\(\n        chat_id=telegram_id,\n        text="✅ \*Evento cadastrado e publicado no grupo\\\\!\*",\n        parse_mode="MarkdownV2",\n    \)',
    re.MULTILINE
)

replacement = """    try:
        import asyncio
        asyncio.create_task(_publicar_evento_no_grupo(request.app.state.telegram_app, id_evento, dict(evento)))
    except Exception as e:
        logger.warning("Falha ao agendar publicacao do evento %s no grupo para %s: %s", id_evento, telegram_id, e)

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text="✅ *Evento cadastrado e publicado no grupo\\\\!*",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning("Falha ao confirmar evento para %s: %s", telegram_id, e)"""

content = api_cadastro_pattern.sub(replacement, content)

with open(r"src\miniapp.py", "w", encoding="utf-8") as f:
    f.write(content)
