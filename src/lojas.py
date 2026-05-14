# src/lojas.py
# ============================================
# BODE ANDARILHO - GERENCIAMENTO DE LOJAS (UX MELHORADO)
# ============================================

from __future__ import annotations

import logging
import asyncio
import json
import mimetypes
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from PIL import Image

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
    listar_membros_por_loja,
    cadastrar_loja,
    excluir_loja,
    atualizar_template_visual_loja,
    buscar_loja_por_nome_numero,
    upload_storage_publico,
)
from src.evento_midia import BUCKET_EVENT_CARDS
from src.permissoes import get_nivel
from src.ritos import normalizar_rito

from src.bot import (
    navegar_para,
    voltar_ao_menu_principal,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO,
)

logger = logging.getLogger(__name__)

# Estados da conversação para cadastro de loja
NOME, NUMERO, ORIENTE, RITO, POTENCIA, ENDERECO, RESPONSAVEL, CONFIRMAR, TEMPLATE_ESCOLHER, TEMPLATE_UPLOAD = range(10)


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


def _teclado_template_pos_cadastro(loja_id: str = "") -> InlineKeyboardMarkup:
    cb_upload = f"loja_template_pos|{loja_id}" if loja_id else "loja_template_menu"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Enviar template agora", callback_data=cb_upload)],
        [InlineKeyboardButton("⏭ Usar padrão por enquanto", callback_data="loja_template_pular")],
        [InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")],
    ])


async def _finalizar_mensagem_cadastro(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    teclado: InlineKeyboardMarkup,
):
    """Finaliza o fluxo no mesmo card de processamento; se necessário, envia uma nova mensagem."""
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
        [InlineKeyboardButton("🖼 Configurar template visual", callback_data="loja_template_menu")],
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
            f"{titulo}\n\nNenhuma loja cadastrada ainda.\n\nCadastre a primeira Loja. O template visual pode ser enviado depois, e enquanto isso o sistema usará o modelo padrão.",
            teclado
        )
        return

    texto = f"{titulo}\n\n"
    botoes_lojas = []
    for i, loja in enumerate(lojas):
        sid = _norm_text(
            loja.get("Telegram ID do secretário responsável")
            or loja.get("secretario_responsavel_id")
            or loja.get("Telegram ID")
        )
        sname = _norm_text(
            loja.get("Nome do secretário responsável")
            or loja.get("secretario_responsavel_nome")
        )
        template_status = "próprio" if _norm_text(loja.get("Template sessão URL") or loja.get("template_sessao_url")) else "padrão do sistema"
        texto += (
            f"🏛 *{loja.get('Nome da Loja')}*"
            f"{' ' + str(loja.get('Número')) if loja.get('Número') else ''}\n"
            f"📍 Oriente: {loja.get('Oriente da Loja', loja.get('Oriente', ''))}\n"
            f"📜 Rito: {loja.get('Rito')}\n"
            f"⚜️ Potência: {loja.get('Potência')}\n"
            f"📍 Endereço: {loja.get('Endereço')}\n"
            f"🖼 Template: {template_status}\n"
            f"👤 Secretário responsável: {sname or sid or 'Não definido'}\n"
            f"━━━━━━━━━━━━━━━━\n"
        )
        nome = loja.get("Nome da Loja", "Loja")
        numero = loja.get("Número", "")
        rotulo = f"👥 {nome}{' ' + str(numero) if numero and str(numero) != '0' else ''}"
        if len(rotulo) > 34:
            rotulo = rotulo[:31] + "..."
        botoes_lojas.append([InlineKeyboardButton(rotulo, callback_data=f"loja_membros|{i}")])

    teclado = InlineKeyboardMarkup(botoes_lojas + [
        [InlineKeyboardButton("➕ Cadastrar nova", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")],
    ])

    await navegar_para(
        update, context,
        "Gerenciamento de Lojas > Minhas Lojas",
        texto,
        teclado
    )


async def ver_membros_da_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os membros vinculados à loja selecionada."""
    query = update.callback_query
    await _safe_answer(query)

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    lojas = listar_lojas_visiveis(user_id, nivel)

    try:
        indice = int((query.data or "").split("|")[1])
    except Exception:
        await query.edit_message_text(
            "Não consegui localizar a loja selecionada.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="loja_listar")]])
        )
        return

    if indice < 0 or indice >= len(lojas):
        await query.edit_message_text(
            "A loja selecionada não está mais disponível.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="loja_listar")]])
        )
        return

    loja = lojas[indice]
    membros = listar_membros_por_loja(
        loja_id=loja.get("ID") or loja.get("id"),
        nome_loja=loja.get("Nome da Loja"),
        numero_loja=loja.get("Número"),
    )

    nome = loja.get("Nome da Loja", "Loja")
    numero = loja.get("Número", "")
    cabecalho = f"🏛 *{nome}*{' ' + str(numero) if numero and str(numero) != '0' else ''}"

    if not membros:
        texto = (
            f"{cabecalho}\n\n"
            "Ainda não encontrei membros vinculados a esta loja.\n\n"
            "Se os irmãos já tiverem sido cadastrados manualmente, podemos vinculá-los nas próximas revisões."
        )
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Voltar às lojas", callback_data="loja_listar")],
        ])
        await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)
        return

    texto = f"{cabecalho}\n\n👥 *Membros vinculados:*\n\n"
    for membro in membros[:40]:
        nome_membro = membro.get("Nome", "Sem nome")
        grau = membro.get("Grau", "Sem grau")
        mi = _norm_text(membro.get("Mestre Instalado") or membro.get("mestre_instalado") or membro.get("mi"))
        vm = _norm_text(membro.get("Venerável Mestre") or membro.get("veneravel_mestre") or membro.get("vm"))
        prefixo = "VM " if vm.lower() == "sim" else ""
        sufixo = " (MI)" if mi.lower() == "sim" and grau == "Mestre" else ""
        texto += f"• {prefixo}{nome_membro} - {grau}{sufixo}\n"

    if len(membros) > 40:
        texto += f"\n... e mais {len(membros) - 40} cadastro(s)."

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Voltar às lojas", callback_data="loja_listar")],
    ])
    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)


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


async def configurar_template_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista lojas para escolher qual receberá template visual."""
    query = update.callback_query
    await _safe_answer(query)

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    lojas = listar_lojas_visiveis(user_id, nivel)
    if not lojas:
        await navegar_para(
            update,
            context,
            "Template Visual",
            "Antes de configurar um template, cadastre sua primeira Loja.\n\nSe o secretário ainda não tiver arte pronta, tudo bem: o sistema usará o template padrão.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Cadastrar primeira loja", callback_data="loja_cadastrar")],
                [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")],
            ]),
        )
        return ConversationHandler.END

    context.user_data["lojas_template_visual"] = lojas
    botoes = []
    for i, loja in enumerate(lojas[:30]):
        nome = loja.get("Nome da Loja", "Loja")
        numero = loja.get("Número", "")
        botoes.append([InlineKeyboardButton(f"🖼 {nome}{' ' + str(numero) if numero else ''}", callback_data=f"loja_template|{i}")])
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")])
    await navegar_para(
        update,
        context,
        "Template Visual",
        "Escolha a loja que receberá o template oficial de sessões:",
        InlineKeyboardMarkup(botoes),
        limpar_conteudo=True,
    )
    return TEMPLATE_ESCOLHER


async def iniciar_upload_template_loja_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await _safe_answer(query)
    data = query.data or ""
    loja_id = data.split("|", 1)[1] if "|" in data else ""
    if not _norm_text(loja_id):
        await query.answer("Não encontrei a loja para configurar.", show_alert=True)
        return ConversationHandler.END
    context.user_data["loja_template_visual_id"] = _norm_text(loja_id)
    await query.edit_message_text(
        "Envie o template oficial da Loja como imagem (foto ou documento PNG/JPG/WEBP).\n\nSe preferir deixar para depois, use /cancelar e a Loja continuará usando o template padrão.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")]]),
    )
    return TEMPLATE_UPLOAD


async def pular_template_pos_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await _safe_answer(query)
        await query.edit_message_text(
            "Tudo certo. A Loja ficará usando o template padrão do sistema por enquanto.\n\nVocê pode trocar depois em Minhas lojas > Configurar template visual.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")]]),
        )
    return ConversationHandler.END


async def escolher_template_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await _safe_answer(query)
    try:
        idx = int((query.data or "").split("|", 1)[1])
    except Exception:
        return TEMPLATE_ESCOLHER
    lojas = context.user_data.get("lojas_template_visual", [])
    if idx < 0 or idx >= len(lojas):
        await query.edit_message_text("Loja não encontrada.")
        return ConversationHandler.END
    loja = lojas[idx]
    context.user_data["loja_template_visual_id"] = str(loja.get("ID") or loja.get("id") or "")
    context.user_data["loja_template_visual_nome"] = str(loja.get("Nome da Loja") or "Loja")
    await query.edit_message_text(
        "Envie o template oficial da Loja como imagem (foto ou documento PNG/JPG/WEBP).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")]]),
    )
    return TEMPLATE_UPLOAD


async def receber_template_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return TEMPLATE_UPLOAD
    loja_id = _norm_text(context.user_data.get("loja_template_visual_id"))
    if not loja_id:
        await msg.reply_text("Não encontrei a loja selecionada. Recomece a configuração.")
        return ConversationHandler.END

    tg_file = None
    filename = "template.jpg"
    content_type = "image/jpeg"
    if msg.photo:
        tg_file = await msg.photo[-1].get_file()
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        tg_file = await msg.document.get_file()
        filename = msg.document.file_name or filename
        content_type = msg.document.mime_type or mimetypes.guess_type(filename)[0] or "image/jpeg"

    if not tg_file:
        await msg.reply_text("Envie uma imagem válida como foto ou documento.")
        return TEMPLATE_UPLOAD

    raw = await tg_file.download_as_bytearray()
    try:
        img = Image.open(BytesIO(raw))
        img.verify()
    except Exception:
        await msg.reply_text("Não consegui validar a imagem. Envie PNG, JPG ou WEBP.")
        return TEMPLATE_UPLOAD

    ext = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg")
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        ext = "jpg"
    url = upload_storage_publico(BUCKET_EVENT_CARDS, f"lojas/{loja_id}/template.{ext}", bytes(raw), content_type)
    if not url:
        await msg.reply_text("Não consegui salvar o template no Supabase Storage. Verifique o bucket event-cards.")
        return TEMPLATE_UPLOAD

    layout = {
        "area_texto": {
            "alinhamento": "center",
            "cor_texto": "#2b1a0c",
            "fundo_translucido": True,
        }
    }
    ok = atualizar_template_visual_loja(loja_id, {
        "Template sessão URL": url,
        "Layout config JSON": json.dumps(layout, ensure_ascii=False),
        "Cor texto padrão": "#2b1a0c",
        "Status template": "Ativo",
    })
    texto = "✅ Template visual configurado com sucesso." if ok else "Template enviado, mas falhei ao atualizar a Loja."
    await msg.reply_text(
        texto,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")]]),
    )
    context.user_data.pop("lojas_template_visual", None)
    context.user_data.pop("loja_template_visual_id", None)
    context.user_data.pop("loja_template_visual_nome", None)
    return ConversationHandler.END


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
    rito_raw = update.message.text.strip()
    rito = normalizar_rito(rito_raw) or rito_raw
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
        
        # Hook Conquistas Coletivas (Marcos Regionais)
        try:
            from src.conquistas import checar_e_disparar_marco_coletivo
            import asyncio
            asyncio.create_task(checar_e_disparar_marco_coletivo(context.bot, dados))
        except Exception:
            pass
            
        loja = buscar_loja_por_nome_numero(dados.get("nome", ""), dados.get("numero", ""))
        loja_id = _norm_text((loja or {}).get("ID") or (loja or {}).get("id"))
        texto = (
            "✅ *Loja cadastrada com sucesso!*\n\n"
            "Agora você pode usar este cadastro como atalho ao criar novos eventos.\n\n"
            "Deseja enviar o template visual oficial desta Loja agora?"
        )
        teclado = _teclado_template_pos_cadastro(loja_id)
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
    context.user_data.pop("lojas_template_visual", None)
    context.user_data.pop("loja_template_visual_id", None)
    context.user_data.pop("loja_template_visual_nome", None)
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
    entry_points=[
        CallbackQueryHandler(cadastrar_loja_inicio, pattern="^loja_cadastrar$"),
        CallbackQueryHandler(configurar_template_menu, pattern="^loja_template_menu$"),
        CallbackQueryHandler(iniciar_upload_template_loja_id, pattern=r"^loja_template_pos\|"),
        CallbackQueryHandler(pular_template_pos_cadastro, pattern="^loja_template_pular$"),
    ],
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
        TEMPLATE_ESCOLHER: [
            CallbackQueryHandler(escolher_template_loja, pattern=r"^loja_template\|"),
            CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
        ],
        TEMPLATE_UPLOAD: [
            MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE), receber_template_loja),
            CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
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
