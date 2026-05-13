from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.bot import TIPO_RESULTADO, _enviar_ou_editar_mensagem, navegar_para
from src.miniapp import WEBAPP_URL_MEMBRO
from src.perfil import mostrar_perfil
from src.sheets_supabase import atualizar_membro, buscar_membro
from src.potencias import (
    formatar_potencia,
    normalizar_potencia,
    potencia_requer_complemento,
    sugestao_complemento,
    validar_potencia,
)

logger = logging.getLogger(__name__)

SELECIONAR_CAMPO, NOVO_VALOR = range(2)

CAMPOS_EDITAVEIS_PERFIL = {
    "nome": {"nome": "Nome civil", "chave": "Nome", "modo": "texto"},
    "data_nasc": {"nome": "Data de nascimento", "chave": "Data de nascimento", "modo": "texto"},
    "grau": {"nome": "Grau", "chave": "Grau", "modo": "inline"},
    "loja": {"nome": "Loja", "chave": "Loja", "modo": "texto"},
    "numero_loja": {"nome": "Número da loja", "chave": "Número da loja", "modo": "texto"},
    "oriente": {"nome": "Oriente", "chave": "Oriente", "modo": "texto"},
    "potencia": {"nome": "Potência", "chave": "Potência", "modo": "inline"},
    "potencia_complemento": {"nome": "Complemento da Potência", "chave": "Potência complemento", "modo": "texto"},
    "mestre_instalado": {"nome": "Mestre Instalado", "chave": "Mestre Instalado", "modo": "inline"},
    "veneravel_mestre": {"nome": "Venerável Mestre", "chave": "Venerável Mestre", "modo": "inline"},
}


def _valor_campo(membro: dict, campo_id: str, campo_info: dict) -> str:
    aliases = {
        "mestre_instalado": ["Mestre Instalado", "mestre_instalado", "mi"],
        "veneravel_mestre": ["Venerável Mestre", "veneravel_mestre", "vm"],
        "data_nasc": ["Data de nascimento", "data_nasc"],
        "numero_loja": ["Número da loja", "numero_loja"],
        "potencia": ["Potência", "potencia"],
        "potencia_complemento": ["Potência complemento", "potencia_complemento", "potencia_outra"],
        "grau": ["Grau", "grau"],
        "loja": ["Loja", "loja"],
        "oriente": ["Oriente", "oriente"],
        "nome": ["Nome", "nome"],
    }
    if campo_id == "potencia":
        principal = ""
        comp = ""
        for chave in aliases.get("potencia", ["Potência"]):
            v = membro.get(chave)
            if v not in (None, ""):
                principal = str(v)
                break
        for chave in aliases.get("potencia_complemento", ["Potência complemento"]):
            v = membro.get(chave)
            if v not in (None, ""):
                comp = str(v)
                break
        if principal or comp:
            return formatar_potencia(principal, comp)
        return "Não informado"
    for chave in aliases.get(campo_id, [campo_info["chave"]]):
        valor = membro.get(chave)
        if valor not in (None, ""):
            return str(valor)
    return "Não informado"


def _teclado_inicio_edicao(membro: dict) -> InlineKeyboardMarkup:
    campos_principais = [
        "nome",
        "data_nasc",
        "grau",
        "mestre_instalado",
        "veneravel_mestre",
        "loja",
        "numero_loja",
        "oriente",
        "potencia",
    ]
    linhas = []
    for campo_id in campos_principais:
        campo_info = CAMPOS_EDITAVEIS_PERFIL[campo_id]
        valor = _valor_campo(membro, campo_id, campo_info)
        linhas.append([
            InlineKeyboardButton(
                f"🛠 {campo_info['nome']}: {valor[:24]}",
                callback_data=f"editar_campo_perfil|{campo_id}",
            )
        ])
    if WEBAPP_URL_MEMBRO:
        linhas.append([
            InlineKeyboardButton(
                "🧾 Editar cadastro completo",
                web_app=WebAppInfo(url=WEBAPP_URL_MEMBRO),
            )
        ])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_opcoes_inline(campo_id: str) -> InlineKeyboardMarkup:
    if campo_id == "grau":
        opcoes = ["Aprendiz", "Companheiro", "Mestre"]
    elif campo_id in {"mestre_instalado", "veneravel_mestre"}:
        opcoes = ["Sim", "Não"]
    elif campo_id == "potencia":
        opcoes = ["GOB", "CMSB", "COMAB"]
    else:
        opcoes = []
    linhas = [[InlineKeyboardButton(valor, callback_data=f"editar_valor_perfil|{campo_id}|{valor}")] for valor in opcoes]
    linhas.append([InlineKeyboardButton("🔙 Voltar", callback_data="editar_perfil")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_complemento_potencia(principal: str) -> InlineKeyboardMarkup:
    principal = (principal or "").strip().upper()
    if principal == "CMSB":
        opcoes = [
            ("GLMERGS", "Grande Loja Maçônica do Estado do Rio Grande do Sul"),
            ("GLSC", "Grande Loja de Santa Catarina"),
            ("GLP", "Grande Loja Maçônica do Estado do Paraná"),
        ]
    elif principal == "COMAB":
        opcoes = [
            ("GORGS", "Grande Oriente do Rio Grande do Sul"),
            ("GOP", "Grande Oriente do Paraná"),
            ("GOSC", "Grande Oriente de Santa Catarina"),
        ]
    else:
        opcoes = [
            ("GOB-RS", "Rio Grande do Sul"),
            ("GOB-SC", "Santa Catarina"),
            ("GOB-PR", "Paraná"),
        ]
    linhas = [
        [InlineKeyboardButton(f"{sigla} - {descricao}", callback_data=f"editar_valor_perfil|potencia_complemento|{sigla}")]
        for sigla, descricao in opcoes
    ]
    linhas.append([InlineKeyboardButton("Outra (texto livre)", callback_data="editar_valor_perfil|potencia_complemento|OUTRA")])
    linhas.append([InlineKeyboardButton("🔙 Voltar", callback_data="editar_campo_perfil|potencia")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_texto_edicao() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Voltar", callback_data="editar_perfil")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
    ])


def _teclado_pos_edicao() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Ver meu perfil", callback_data="meu_cadastro")],
        [InlineKeyboardButton("✏️ Ajustar outro campo", callback_data="editar_perfil")],
    ])


def _mensagem_prompt_campo(campo_info: dict, valor_atual: str, observacao: str = "") -> str:
    linhas = [
        f"✏️ *Retificação de {campo_info['nome']}*",
        "",
        f"Informação atual: `{valor_atual}`",
        "",
        "Escreva o novo dado abaixo ou use os botões para voltar.",
    ]
    observacao = str(observacao or "").strip()
    if observacao:
        linhas.extend(["", observacao])
    return "\n".join(linhas)


async def _mostrar_prompt_campo_texto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campo_id: str,
    observacao: str = "",
):
    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)
    if not campo_info:
        return ConversationHandler.END

    membro = buscar_membro(update.effective_user.id) or context.user_data.get("perfil_dados", {})
    context.user_data["perfil_dados"] = membro
    context.user_data["editando_campo_perfil"] = campo_id
    valor_atual = _valor_campo(membro, campo_id, campo_info)

    await navegar_para(
        update,
        context,
        f"Retificar {campo_info['nome']}",
        _mensagem_prompt_campo(campo_info, valor_atual, observacao),
        _teclado_texto_edicao(),
        limpar_conteudo=True,
    )
    return NOVO_VALOR


async def editar_perfil_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if not membro:
        await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            "Saudações, Irmão. Identificamos que ainda não possuís cadastro. Por favor, utilize o comando /start para iniciar nossa caminhada.",
        )
        return ConversationHandler.END

    context.user_data["perfil_dados"] = membro
    await navegar_para(
        update,
        context,
        "Ajustar Cadastro",
        "Escolha o ponto do cadastro que deseja ajustar. Para mudanças maiores, use a revisão completa no Mini App.",
        _teclado_inicio_edicao(membro),
    )
    return SELECIONAR_CAMPO


async def selecionar_campo_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    campo_id = query.data.split("|")[1]
    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)
    if not campo_info:
        return ConversationHandler.END

    context.user_data["editando_campo_perfil"] = campo_id
    membro = buscar_membro(update.effective_user.id) or context.user_data.get("perfil_dados", {})
    context.user_data["perfil_dados"] = membro
    valor_atual = _valor_campo(membro, campo_id, campo_info)

    if campo_info["modo"] == "inline":
        await navegar_para(
            update,
            context,
            f"Ajustar {campo_info['nome']}",
            f"Valor atual: `{valor_atual}`\n\nEscolha abaixo como deseja atualizar este campo.",
            _teclado_opcoes_inline(campo_id),
        )
        return SELECIONAR_CAMPO

    return await _mostrar_prompt_campo_texto(update, context, campo_id)


async def aplicar_valor_inline_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, campo_id, novo_valor = query.data.split("|", 2)
    user_id = update.effective_user.id

    if campo_id == "potencia":
        principal, _ = normalizar_potencia(novo_valor, "")
        if potencia_requer_complemento(principal):
            context.user_data["potencia_principal_pendente"] = principal
            context.user_data["editando_campo_perfil"] = "potencia_complemento"
            await navegar_para(
                update,
                context,
                "Retificar Potência",
                (
                    f"Potência principal selecionada: *{principal}*\n\n"
                    "Selecione o complemento abaixo ou escolha *Outra* para digitar manualmente."
                ),
                _teclado_complemento_potencia(principal),
                limpar_conteudo=True,
            )
            return SELECIONAR_CAMPO

    if campo_id == "potencia_complemento":
        principal_pendente = (context.user_data.get("potencia_principal_pendente") or "").strip()
        if not principal_pendente:
            await query.answer("Selecione primeiro a Potência principal.", show_alert=True)
            return ConversationHandler.END
        if novo_valor == "OUTRA":
            return await _mostrar_prompt_campo_texto(
                update,
                context,
                "potencia_complemento",
                f"Informe o complemento da potência. {sugestao_complemento(principal_pendente)}",
            )
        principal, comp = normalizar_potencia(principal_pendente, novo_valor)
        if not validar_potencia(principal, comp):
            await query.answer("Complemento inválido.", show_alert=True)
            return SELECIONAR_CAMPO
        sucesso = atualizar_membro(
            user_id,
            {
                CAMPOS_EDITAVEIS_PERFIL["potencia"]["chave"]: principal,
                CAMPOS_EDITAVEIS_PERFIL["potencia_complemento"]["chave"]: comp,
            },
            preservar_nivel=True,
        )
        if not sucesso:
            await query.answer("Não consegui atualizar este dado agora.", show_alert=True)
            return ConversationHandler.END
        await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            "✅ Potência atualizada com sucesso.\n\nUse o menu abaixo para seguir.",
            _teclado_pos_edicao(),
            limpar_conteudo=True,
        )
        context.user_data.pop("potencia_principal_pendente", None)
        context.user_data.pop("editando_campo_perfil", None)
        context.user_data.pop("perfil_dados", None)
        return ConversationHandler.END

    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)
    if not campo_info:
        return ConversationHandler.END

    if campo_id == "potencia":
        principal, comp = normalizar_potencia(novo_valor, "")
        if not validar_potencia(principal, comp):
            await query.answer("Potência inválida.", show_alert=True)
            return ConversationHandler.END
        sucesso = atualizar_membro(
            user_id,
            {
                CAMPOS_EDITAVEIS_PERFIL["potencia"]["chave"]: principal,
                CAMPOS_EDITAVEIS_PERFIL["potencia_complemento"]["chave"]: "",
            },
            preservar_nivel=True,
        )
    else:
        sucesso = atualizar_membro(user_id, {campo_info["chave"]: novo_valor}, preservar_nivel=True)
    if not sucesso:
        await query.answer("Não consegui atualizar este dado agora.", show_alert=True)
        return ConversationHandler.END

    await _enviar_ou_editar_mensagem(
        context,
        user_id,
        TIPO_RESULTADO,
        f"✅ O campo *{campo_info['nome']}* foi atualizado com sucesso.\n\nUse o menu abaixo para seguir.",
        _teclado_pos_edicao(),
        limpar_conteudo=True,
    )
    context.user_data.pop("editando_campo_perfil", None)
    context.user_data.pop("perfil_dados", None)
    return ConversationHandler.END


async def receber_novo_valor_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("editando_campo_perfil")
    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)
    if not campo_info:
        return ConversationHandler.END

    if campo_id in {"mestre_instalado", "veneravel_mestre"}:
        normalizado = novo_valor.lower()
        if normalizado in {"sim", "s"}:
            novo_valor = "Sim"
        elif normalizado in {"não", "nao", "n"}:
            novo_valor = "Não"
        else:
            return await _mostrar_prompt_campo_texto(
                update,
                context,
                campo_id,
                "Irmão, para este campo, responda apenas com *Sim* ou *Não*.",
            )

    if campo_id == "potencia_complemento":
        principal_pendente = (context.user_data.get("potencia_principal_pendente") or "").strip()
        if principal_pendente:
            principal, comp = normalizar_potencia(principal_pendente, novo_valor)
            if not validar_potencia(principal, comp):
                return await _mostrar_prompt_campo_texto(
                    update,
                    context,
                    campo_id,
                    "Complemento inválido. Ex.: GLMERGS, GOB-RS, GORGS.",
                )
            sucesso = atualizar_membro(
                update.effective_user.id,
                {
                    CAMPOS_EDITAVEIS_PERFIL["potencia"]["chave"]: principal,
                    CAMPOS_EDITAVEIS_PERFIL["potencia_complemento"]["chave"]: comp,
                },
                preservar_nivel=True,
            )
        else:
            membro = buscar_membro(update.effective_user.id) or {}
            pot_atual = _valor_campo(membro, "potencia", CAMPOS_EDITAVEIS_PERFIL["potencia"])
            principal, _ = normalizar_potencia(pot_atual, "")
            principal = principal or "CMSB"
            principal, comp = normalizar_potencia(principal, novo_valor)
            if not validar_potencia(principal, comp):
                return await _mostrar_prompt_campo_texto(
                    update,
                    context,
                    campo_id,
                    "Complemento inválido. Ex.: GLMERGS, GOB-RS, GORGS.",
                )
            sucesso = atualizar_membro(
                update.effective_user.id,
                {CAMPOS_EDITAVEIS_PERFIL["potencia_complemento"]["chave"]: comp},
                preservar_nivel=True,
            )
    else:
        sucesso = atualizar_membro(update.effective_user.id, {campo_info["chave"]: novo_valor}, preservar_nivel=True)
    if sucesso:
        await _enviar_ou_editar_mensagem(
            context,
            update.effective_user.id,
            TIPO_RESULTADO,
            f"✅ O campo *{campo_info['nome']}* foi atualizado com sucesso.\n\nUse o menu abaixo para seguir.",
            _teclado_pos_edicao(),
            limpar_conteudo=True,
        )
    else:
        return await _mostrar_prompt_campo_texto(
            update,
            context,
            campo_id,
            "Houve um percalço ao atualizar seus dados. Tente novamente em alguns instantes.",
        )

    context.user_data.pop("editando_campo_perfil", None)
    context.user_data.pop("perfil_dados", None)
    context.user_data.pop("potencia_principal_pendente", None)
    return ConversationHandler.END


async def cancelar_edicao_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "A retificação foi interrompida. Seus dados permanecem inalterados e acobertos."
    if update.callback_query:
        await update.callback_query.answer()
    await _enviar_ou_editar_mensagem(
        context,
        update.effective_user.id,
        TIPO_RESULTADO,
        msg,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Ver meu perfil", callback_data="meu_cadastro")],
            [InlineKeyboardButton("🏠 Início", callback_data="menu_principal")],
        ]),
        limpar_conteudo=True,
    )
    context.user_data.clear()
    return ConversationHandler.END


editar_perfil_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_perfil_inicio, pattern="^editar_perfil$")],
    states={
        SELECIONAR_CAMPO: [
            CallbackQueryHandler(selecionar_campo_perfil, pattern=r"^editar_campo_perfil\|"),
            CallbackQueryHandler(aplicar_valor_inline_perfil, pattern=r"^editar_valor_perfil\|"),
            CallbackQueryHandler(cancelar_edicao_perfil, pattern="^cancelar$"),
            CallbackQueryHandler(editar_perfil_inicio, pattern="^editar_perfil$"),
        ],
        NOVO_VALOR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_perfil),
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_edicao_perfil),
        CallbackQueryHandler(cancelar_edicao_perfil, pattern="^cancelar$"),
    ],
)
