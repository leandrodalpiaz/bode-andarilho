# src/lojas.py
# ============================================
# BODE ANDARILHO - GERENCIAMENTO DE LOJAS (UX MELHORADO)
# ============================================

from __future__ import annotations

import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.miniapp import WEBAPP_URL_LOJA  # noqa: E402
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from src.sheets_supabase import (
    listar_lojas_visiveis,
    listar_secretarios_ativos,
    cadastrar_loja,
    excluir_loja,
)
from src.permissoes import get_nivel

from src.bot import (
    navegar_para,
    voltar_ao_menu_principal,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO,
)

logger = logging.getLogger(__name__)

# Estados da conversação para cadastro de loja
NOME, NUMERO, ORIENTE, RITO, POTENCIA, ENDERECO, RESPONSAVEL, CONFIRMAR = range(8)


# ============================================
# FUNÇÕES AUXILIARES
# ============================================

async def _safe_edit(query, text: str, **kwargs):
    """Edita mensagem ignorando erro 'Message not modified'."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


async def _safe_answer(query, text: str | None = None):
    """Responde callback sem quebrar fluxo quando o query expira no Telegram."""
    try:
        if text:
            await query.answer(text)
        else:
            await query.answer()
    except BadRequest as e:
        msg = str(e)
        if "Query is too old" in msg or "query id is invalid" in msg:
            logger.warning("Callback expirado/invalidado ignorado: %s", msg)
        else:
            raise


def _norm_text(valor: object) -> str:
    """Normaliza texto para uso em contexto/armazenamento."""
    if valor is None:
        return ""
    return str(valor).strip()


def _resumo_loja_markdown(dados: dict) -> str:
    """Monta resumo da loja para confirmação."""
    responsavel = _norm_text(dados.get("secretario_responsavel_nome")) or _norm_text(
        dados.get("secretario_responsavel_id")
    )
    responsavel_linha = f"*Secretário responsável:* {responsavel}\n" if responsavel else ""
    return (
        f"🏛️ *Confirme os dados da loja:*\n\n"
        f"*Nome:* {dados.get('nome', '')}\n"
        f"*Número:* {dados.get('numero', '')}\n"
        f"*Oriente:* {dados.get('oriente', '')}\n"
        f"*Rito:* {dados.get('rito', '')}\n"
        f"*Potência:* {dados.get('potencia', '')}\n"
        f"*Endereço:* {dados.get('endereco', '')}\n"
        f"{responsavel_linha}\n"
        f"Tudo correto?"
    )


def _teclado_selecionar_secretario(secretarios: list[dict]) -> InlineKeyboardMarkup:
    """Teclado para admin escolher secretário responsável da loja."""
    botoes = []
    for sec in secretarios[:30]:
        sid = _norm_text(sec.get("telegram_id"))
        nome = _norm_text(sec.get("nome")) or sid
        if sid:
            botoes.append([InlineKeyboardButton(f"👤 {nome}", callback_data=f"loja_secretario|{sid}")])
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")])
    return InlineKeyboardMarkup(botoes)


async def _finalizar_mensagem_cadastro(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    teclado: InlineKeyboardMarkup,
):
    """Finaliza o fluxo no mesmo card de processamento; se necess?rio, envia uma nova mensagem."""
    query = update.callback_query
    user_id = update.effective_user.id

    try:
        if query and query.message:
            await query.edit_message_text(
                text=texto,
                parse_mode="Markdown",
                reply_markup=teclado,
            )
            logger.info("Cadastro loja: mensagem final entregue por edicao do card de processamento (user_id=%s)", user_id)
            return
    except BadRequest as e:
        msg = str(e)
        if "Message is not modified" in msg:
            return
        logger.warning("Falha ao editar card final de cadastro de loja: %s", msg)
    except Exception as e:
        logger.warning("Falha inesperada ao editar card final de cadastro de loja: %s", e)

    await context.bot.send_message(
        chat_id=user_id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=teclado,
    )
    logger.info("Cadastro loja: mensagem final entregue por envio de novo card (user_id=%s)", user_id)


# ============================================
# MENU PRINCIPAL DE LOJAS
# ============================================

async def menu_lojas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Menu principal para gerenciar lojas.
    Exibe opções de cadastrar nova loja, listar as existentes, excluir ou voltar.
    """
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Apenas secretários e administradores podem acessar esta função."
        )
        return

    rotulo_lista = "📋 Listar todas as lojas" if nivel == "3" else "📋 Listar minhas lojas"
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Cadastrar nova loja", callback_data="loja_cadastrar")],
        [InlineKeyboardButton(rotulo_lista, callback_data="loja_listar")],
        [InlineKeyboardButton("❌ Excluir loja", callback_data="loja_excluir_menu")],
        [InlineKeyboardButton("🏠 Menu Principal", callback_data="menu_principal")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")],
    ])

    await navegar_para(
        update, context,
        "Gerenciamento de Lojas",
        "🏛️ *Gerenciamento de Lojas*\n\n"
        + (
            "Aqui você pode cadastrar e manter todas as lojas, incluindo o secretário responsável de cada uma."
            if nivel == "3"
            else "Aqui você pode cadastrar os dados fixos da sua loja para usar como atalho ao criar novos eventos."
        ),
        teclado
    )


# ============================================
# LISTAR LOJAS CADASTRADAS
# ============================================

async def listar_lojas_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista as lojas cadastradas pelo secretário."""
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    lojas = listar_lojas_visiveis(user_id, nivel)
    titulo = "📋 *Todas as Lojas*" if nivel == "3" else "📋 *Minhas Lojas*"

    if not lojas:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Cadastrar nova loja", callback_data="loja_cadastrar")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")],
        ])
        await navegar_para(
            update, context,
            "Gerenciamento de Lojas > Minhas Lojas",
            f"{titulo}\n\nNenhuma loja cadastrada.",
            teclado
        )
        return

    texto = f"{titulo}\n\n"
    for loja in lojas:
        sid = _norm_text(
            loja.get("Telegram ID do secretário responsável")
            or loja.get("secretario_responsavel_id")
            or loja.get("Telegram ID")
        )
        sname = _norm_text(
            loja.get("Nome do secretário responsável")
            or loja.get("secretario_responsavel_nome")
        )
        texto += (
            f"🏛 *{loja.get('Nome da Loja')}*"
            f"{' ' + str(loja.get('Número')) if loja.get('Número') else ''}\n"
            f"📍 Oriente: {loja.get('Oriente da Loja', loja.get('Oriente', ''))}\n"
            f"📜 Rito: {loja.get('Rito')}\n"
            f"⚜️ Potência: {loja.get('Potência')}\n"
            f"📍 Endereço: {loja.get('Endereço')}\n"
            f"👤 Secretário responsável: {sname or sid or 'Não definido'}\n"
            f"━━━━━━━━━━━━━━━━\n"
        )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Cadastrar nova", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")],
    ])

    await navegar_para(
        update, context,
        "Gerenciamento de Lojas > Minhas Lojas",
        texto,
        teclado
    )


# ============================================
# EXCLUSÃO DE LOJAS (UX MELHORADO)
# ============================================

async def excluir_loja_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe lista de lojas para o usuário escolher qual excluir."""
    query = update.callback_query
    await _safe_answer(query)

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    lojas = listar_lojas_visiveis(user_id, nivel)

    if not lojas:
        await query.edit_message_text(
            "📭 *Nenhuma loja cadastrada para excluir.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")
            ]])
        )
        return

    texto = "❌ *Selecione a loja que deseja excluir:*\n\n"
    teclado = []

    for i, loja in enumerate(lojas):
        nome = loja.get('Nome da Loja', 'Sem nome')
        numero = loja.get('Número', '')
        identificacao = f"{nome} {numero}".strip()
        teclado.append([InlineKeyboardButton(
            f"🗑 {identificacao}",
            callback_data=f"excluir_loja_{i}"
        )])

    teclado.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")])

    await query.edit_message_text(
        texto,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(teclado)
    )
    # Guarda a lista de lojas no user_data para usar depois
    context.user_data["lojas_para_excluir"] = lojas


async def confirmar_exclusao_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pede confirmação antes de excluir a loja selecionada."""
    query = update.callback_query
    await _safe_answer(query)

    data = query.data
    if not data.startswith("excluir_loja_"):
        return

    try:
        indice = int(data.split("_")[2])
    except (IndexError, ValueError):
        await query.edit_message_text("❌ Erro ao identificar a loja.")
        return

    lojas = context.user_data.get("lojas_para_excluir", [])
    if indice < 0 or indice >= len(lojas):
        await query.edit_message_text("❌ Loja não encontrada.")
        return

    # Guarda o índice para a exclusão efetiva
    context.user_data["excluir_loja_indice"] = indice
    loja = lojas[indice]
    nome = loja.get('Nome da Loja', 'esta loja')

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, excluir", callback_data="excluir_loja_confirmar")],
        [InlineKeyboardButton("🔙 Não, voltar", callback_data="loja_excluir_menu")],
    ])

    await query.edit_message_text(
        f"⚠️ *Tem certeza que deseja excluir a loja:*\n\n🏛 {nome}?\n\nEsta ação não pode ser desfeita.",
        parse_mode="Markdown",
        reply_markup=teclado
    )


async def executar_exclusao_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa a exclusão da loja após confirmação."""
    query = update.callback_query
    await _safe_answer(query)

    # Feedback imediato de processamento
    try:
        await query.edit_message_text(
            text="🔄 *Processando exclusão...*",
            parse_mode="Markdown",
            reply_markup=None
        )
    except Exception as e:
        logger.warning(f"Erro ao editar mensagem para feedback: {e}")

    indice = context.user_data.get("excluir_loja_indice")
    lojas = context.user_data.get("lojas_para_excluir", [])

    if indice is None or indice >= len(lojas):
        await query.edit_message_text(
            "❌ Erro: dados da exclusão não encontrados. Tente novamente.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_lojas")
            ]])
        )
        return

    loja = lojas[indice]
    # A função excluir_loja precisa do identificador único. Como a planilha pode não ter ID,
    # vamos usar uma combinação de nome e número ou assumir que excluir_loja usa o nome + número.
    # Vou adaptar: vamos passar o dicionário da loja.
    sucesso = excluir_loja(update.effective_user.id, loja)

    await asyncio.sleep(0.5)  # pequena pausa para UX

    if sucesso:
        logger.info(f"Loja excluída com sucesso: {loja.get('Nome da Loja')}")
        texto = "✅ *Loja excluída com sucesso!*"
    else:
        logger.error(f"Falha ao excluir loja: {loja.get('Nome da Loja')}")
        texto = "❌ *Erro ao excluir loja. Tente novamente mais tarde.*"

    # Limpa dados da exclusão
    context.user_data.pop("excluir_loja_indice", None)
    context.user_data.pop("lojas_para_excluir", None)

    await navegar_para(
        update, context,
        "Exclusão de Loja",
        texto,
        InlineKeyboardMarkup([[
            InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")
        ]])
    )


# ============================================
# CADASTRO DE NOVA LOJA (CONVERSATION HANDLER)
# ============================================

async def cadastrar_loja_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o cadastro de uma nova loja."""
    query = update.callback_query
    if query:
        await _safe_answer(query, "🏛️ Iniciando cadastro...")

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return ConversationHandler.END

    context.user_data["nova_loja"] = {}
    context.user_data.pop("secretarios_disponiveis_loja", None)
    context.user_data["nova_loja_operador_id"] = str(user_id)
    context.user_data["nova_loja_nivel"] = str(nivel)

    # Mini App: secretários podem usar webform; admin segue fluxo guiado para escolher responsável.
    if WEBAPP_URL_LOJA and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🏙️ *Cadastrar nova loja*\n\nToque no botão abaixo para preencher o formulário:",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("📋 Abrir formulário", web_app=WebAppInfo(url=WEBAPP_URL_LOJA))]]
            ),
        )
        return ConversationHandler.END

    await navegar_para(
        update, context,
        "Cadastro de Loja",
        "🏛️ *Cadastro de Loja*\n\nQual o *nome da loja*?",
        InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]])
    )
    return NOME


async def receber_nome_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o nome da loja."""
    nome = update.message.text.strip()
    if len(nome) < 2:
        await update.message.reply_text("❌ Nome muito curto. Digite novamente:")
        return NOME

    context.user_data["nova_loja"]["nome"] = nome

    await update.message.reply_text(
        "🔢 *Número da loja* (Digite 0 se não houver)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return NUMERO


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o número da loja."""
    numero = update.message.text.strip()
    if not numero.isdigit() and numero != "0":
        await update.message.reply_text("❌ Digite apenas números (ou 0):")
        return NUMERO

    context.user_data["nova_loja"]["numero"] = numero

    await update.message.reply_text(
        "📍 *Oriente da Loja* (cidade da loja)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return ORIENTE


async def receber_oriente_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o oriente da loja."""
    oriente = update.message.text.strip()
    if len(oriente) < 2:
        await update.message.reply_text("❌ Oriente muito curto. Digite novamente:")
        return ORIENTE

    context.user_data["nova_loja"]["oriente"] = oriente

    await update.message.reply_text(
        "📜 *Rito*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return RITO


async def receber_rito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o rito."""
    rito = update.message.text.strip()
    if len(rito) < 2:
        await update.message.reply_text("❌ Rito muito curto. Digite novamente:")
        return RITO

    context.user_data["nova_loja"]["rito"] = rito

    await update.message.reply_text(
        "⚜️ *Potência*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a potência."""
    potencia = update.message.text.strip()
    if len(potencia) < 2:
        await update.message.reply_text("❌ Potência muito curta. Digite novamente:")
        return POTENCIA

    context.user_data["nova_loja"]["potencia"] = potencia

    await update.message.reply_text(
        "📍 *Endereço* da loja?\n"
        "(Pode ser texto ou link do Google Maps)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return ENDERECO


async def receber_endereco_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o endereço e mostra resumo para confirmação."""
    endereco = update.message.text.strip()
    if len(endereco) < 3:
        await update.message.reply_text("❌ Endereço muito curto. Digite novamente:")
        return ENDERECO

    context.user_data["nova_loja"]["endereco"] = endereco
    dados = context.user_data["nova_loja"]
    nivel = _norm_text(context.user_data.get("nova_loja_nivel"))

    if nivel == "3":
        secretarios = listar_secretarios_ativos()
        if not secretarios:
            await update.message.reply_text("❌ Não há secretários ativos para vincular a esta loja.")
            return ConversationHandler.END
        context.user_data["secretarios_disponiveis_loja"] = secretarios
        await update.message.reply_text(
            "👤 *Selecione o secretário responsável por esta loja:*",
            parse_mode="Markdown",
            reply_markup=_teclado_selecionar_secretario(secretarios),
        )
        return RESPONSAVEL

    resumo = _resumo_loja_markdown(dados)

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, cadastrar", callback_data="confirmar_cadastro_loja")],
        [InlineKeyboardButton("🔄 Recomeçar", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")],
    ])

    await update.message.reply_text(resumo, parse_mode="Markdown", reply_markup=teclado)
    return CONFIRMAR


async def selecionar_secretario_loja_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Define o secretário responsável da loja (fluxo admin)."""
    query = update.callback_query
    await _safe_answer(query)
    data = query.data or ""

    if not data.startswith("loja_secretario|"):
        return RESPONSAVEL

    sid = _norm_text(data.split("|", 1)[1])
    secretarios = context.user_data.get("secretarios_disponiveis_loja", [])
    nome = ""
    for sec in secretarios:
        if _norm_text(sec.get("telegram_id")) == sid:
            nome = _norm_text(sec.get("nome"))
            break

    dados = context.user_data.get("nova_loja", {})
    dados["secretario_responsavel_id"] = sid
    dados["secretario_responsavel_nome"] = nome
    context.user_data["nova_loja"] = dados

    resumo = _resumo_loja_markdown(dados)
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, cadastrar", callback_data="confirmar_cadastro_loja")],
        [InlineKeyboardButton("🔄 Recomeçar", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")],
    ])
    await query.edit_message_text(resumo, parse_mode="Markdown", reply_markup=teclado)
    return CONFIRMAR


async def confirmar_cadastro_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e salva a loja na planilha."""
    query = update.callback_query
    user_id = update.effective_user.id

    # Responde primeiro para evitar expiração do callback em operações mais lentas.
    await _safe_answer(query, "✅ Processando...")

    # Feedback imediato
    try:
        await query.edit_message_text(
            text="🔄 *Processando seu cadastro...*\n\nAguarde um momento.",
            parse_mode="Markdown",
            reply_markup=None
        )
    except Exception as e:
        logger.warning(f"Erro ao editar mensagem para feedback: {e}")

    dados = context.user_data.get("nova_loja", {})
    operador_id = _norm_text(context.user_data.get("nova_loja_operador_id")) or str(user_id)

    if not dados:
        logger.error(f"Erro: dados não encontrados para usuário {user_id}")
        await asyncio.sleep(0.5)
        await _finalizar_mensagem_cadastro(
            update,
            context,
            "❌ *Erro: dados não encontrados.*\n\nTente novamente.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏛️ Voltar ao menu de lojas", callback_data="menu_lojas")]]
            ),
        )
        return ConversationHandler.END

    try:
        dados.setdefault("vinculo_atualizado_por_id", operador_id)
        sucesso = await asyncio.to_thread(cadastrar_loja, user_id, dados)
    except Exception as e:
        logger.error("Erro inesperado ao cadastrar loja para %s: %s", user_id, e, exc_info=True)
        sucesso = False

    await asyncio.sleep(0.5)

    if sucesso:
        logger.info(f"Loja cadastrada com sucesso para usuário {user_id}: {dados.get('nome')}")
        texto = "✅ *Loja cadastrada com sucesso!*\n\nAgora você pode usar este cadastro como atalho ao criar novos eventos."
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")],
            [InlineKeyboardButton("🏠 Menu Principal", callback_data="menu_principal")]
        ])
    else:
        logger.error(f"Erro ao cadastrar loja para usuário {user_id}: {dados.get('nome')}")
        texto = "❌ *Erro ao cadastrar loja.*\n\nTente novamente mais tarde."
        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏛️ Voltar ao menu de lojas", callback_data="menu_lojas")
        ]])

    await _finalizar_mensagem_cadastro(update, context, texto, teclado)

    context.user_data.pop("nova_loja", None)
    context.user_data.pop("secretarios_disponiveis_loja", None)
    context.user_data.pop("nova_loja_nivel", None)
    context.user_data.pop("nova_loja_operador_id", None)
    return ConversationHandler.END


async def cancelar_cadastro_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o cadastro de loja."""
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        await _safe_answer(query)
        await navegar_para(
            update, context,
            "Cadastro de Loja",
            "Cadastro cancelado.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Voltar ao menu de lojas", callback_data="menu_lojas")
            ]])
        )
    else:
        if update.message:
            await update.message.reply_text("Cadastro cancelado.")

    context.user_data.pop("nova_loja", None)
    context.user_data.pop("secretarios_disponiveis_loja", None)
    context.user_data.pop("nova_loja_nivel", None)
    context.user_data.pop("nova_loja_operador_id", None)
    return ConversationHandler.END


# ============================================
# CONVERSATION HANDLER (CADASTRO)
# ============================================

cadastro_loja_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(cadastrar_loja_inicio, pattern="^loja_cadastrar$")],
    states={
        NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome_loja)],
        NUMERO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_numero_loja)],
        ORIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_oriente_loja)],
        RITO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_rito)],
        POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
        ENDERECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_endereco_loja)],
        RESPONSAVEL: [
            CallbackQueryHandler(selecionar_secretario_loja_callback, pattern=r"^loja_secretario\|"),
            CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
        ],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_cadastro_loja, pattern="^confirmar_cadastro_loja$"),
            CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
            CallbackQueryHandler(cadastrar_loja_inicio, pattern="^loja_cadastrar$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_cadastro_loja),
        CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
    ],
    name="cadastro_loja_handler",
    persistent=False,
)


# ============================================
# HANDLERS SIMPLES (PARA REGISTRO NO MAIN.PY)
# ============================================

listar_lojas_handler_cb = CallbackQueryHandler(listar_lojas_handler, pattern="^loja_listar$")
menu_lojas_handler = CallbackQueryHandler(menu_lojas, pattern="^menu_lojas$")
excluir_loja_menu_handler = CallbackQueryHandler(excluir_loja_menu, pattern="^loja_excluir_menu$")
confirmar_exclusao_loja_handler = CallbackQueryHandler(confirmar_exclusao_loja, pattern="^excluir_loja_\\d+$")
executar_exclusao_loja_handler = CallbackQueryHandler(executar_exclusao_loja, pattern="^excluir_loja_confirmar$")
