# src/cadastro.py
# ============================================
# BODE ANDARILHO - CADASTRO DE MEMBROS
# ============================================
# 
# Este módulo gerencia o cadastro de novos membros e a edição
# do próprio cadastro pelo usuário.
# 
# Funcionalidades:
# - Cadastro completo com validação de dados
# - Edição de cadastro existente
# - Navegação com botões Voltar/Cancelar
# - Integração com confirmação de presença (pos_cadastro)
# 
# Utiliza um ConversationHandler com 9 estados sequenciais.
# 
# ============================================

from __future__ import annotations

import logging
import re
import traceback
import unicodedata
from datetime import datetime
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo

from src.miniapp import WEBAPP_URL_MEMBRO  # noqa: E402
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.messages import (
    CADASTRO_CANCELADO,
    CADASTRO_CONCLUIDO,
    ERRO_GENERICO,
    CADASTRO_REDIRECIONAR_PRIVADO,
    CADASTRO_REVALIDACAO_NECESSARIA,
    CADASTRO_PARCIAL_EM_ANDAMENTO,
    CADASTRO_BOAS_VINDAS_GRUPO,
    CADASTRO_INICIO_PADRAO,
    CADASTRO_NOVO_INTRO_TMPL,
    CADASTRO_REVALIDAR_INTRO_TMPL,
    CADASTRO_ERRO_NOME_CURTO,
    CADASTRO_ERRO_DATA_NASC,
    CADASTRO_ERRO_LOJA,
    CADASTRO_ERRO_NUMERO_LOJA,
    CADASTRO_ERRO_ORIENTE,
    CADASTRO_ERRO_POTENCIA,
    CADASTRO_ERRO_GRAU_TEXTO,
    CADASTRO_ERRO_VM_TEXTO,
    CADASTRO_ERRO_GRAU_INVALIDO,
    CADASTRO_ERRO_GRAU_SELECIONE,
    CADASTRO_ERRO_VM_INVALIDO,
    CADASTRO_REVISAO_FINAL_TMPL,
    CADASTRO_DADOS_PENDENTES,
    CADASTRO_FALHA_SALVAR,
    CADASTRO_PROMPT_CONFIRMAR,
    CADASTRO_OPERACAO_CANCELADA,
)
from src.sheets_supabase import buscar_membro, cadastrar_membro
from src.bot import (
    navegar_para,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

# Estados da conversação
NOME, DATA_NASC, GRAU, VM, LOJA, NUMERO_LOJA, ORIENTE, POTENCIA, CONFIRMAR = range(9)

# Opções fixas
GRAUS_OPCOES = [
    "Aprendiz",
    "Companheiro",
    "Mestre",
    "Mestre Instalado",
]

VM_SIM = "Sim"
VM_NAO = "Não"

CADASTRO_ETAPAS = (
    "cadastro_nome",
    "cadastro_data_nasc",
    "cadastro_grau",
    "cadastro_vm",
    "cadastro_loja",
    "cadastro_numero_loja",
    "cadastro_oriente",
    "cadastro_potencia",
)


def _normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparações tolerantes a acentos e caixa."""
    base = (texto or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", base)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _campo_preenchido(context: ContextTypes.DEFAULT_TYPE, chave: str) -> bool:
    return bool((context.user_data.get(chave) or "").strip())


def _cadastro_parcial_em_andamento(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Indica se existe algum dado parcial de cadastro no contexto."""
    return any(_campo_preenchido(context, chave) for chave in CADASTRO_ETAPAS)


def _estado_pendente_cadastro(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Retorna o próximo estado pendente para completar o cadastro."""
    if not _campo_preenchido(context, "cadastro_nome"):
        return NOME
    if not _campo_preenchido(context, "cadastro_data_nasc"):
        return DATA_NASC
    if not _campo_preenchido(context, "cadastro_grau"):
        return GRAU
    if not _campo_preenchido(context, "cadastro_vm"):
        return VM
    if not _campo_preenchido(context, "cadastro_loja"):
        return LOJA
    if not _campo_preenchido(context, "cadastro_numero_loja"):
        return NUMERO_LOJA
    if not _campo_preenchido(context, "cadastro_oriente"):
        return ORIENTE
    if not _campo_preenchido(context, "cadastro_potencia"):
        return POTENCIA
    return CONFIRMAR


def _texto_etapa(estado: int, retomada: bool = False) -> str:
    """Texto guia para cada etapa, com linguagem de passo a passo."""
    prefixo = "▶️ *Retomando cadastro*\n\n" if retomada else ""
    textos = {
        NOME: "🧭 *Passo 1/8*\nEnvie seu *nome completo*.",
        DATA_NASC: "🧭 *Passo 2/8*\nEnvie sua *data de nascimento* no formato DD/MM/AAAA.\nEx.: 25/03/1988",
        GRAU: "🧭 *Passo 3/8*\nSelecione seu *grau*.",
        VM: "🧭 *Passo 4/8*\nVocê é *Venerável Mestre*?",
        LOJA: "🧭 *Passo 5/8*\nInforme o *nome da sua loja*.",
        NUMERO_LOJA: "🧭 *Passo 6/8*\nInforme o *número da sua loja* (somente números).\nEx.: 12 ou 0",
        ORIENTE: "🧭 *Passo 7/8*\nInforme seu *Oriente*.",
        POTENCIA: "🧭 *Passo 8/8*\nInforme sua *Potência*.",
    }
    return f"{prefixo}{textos.get(estado, 'Envie a informação solicitada:')}"


async def _responder_callback_seguro(query) -> None:
    """Responde callback sem quebrar o fluxo quando a query expirou."""
    if not query:
        return
    try:
        await query.answer()
    except Exception as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.debug("Callback expirado no cadastro (ignorado): %s", e)
            return
        logger.warning("Falha ao responder callback no cadastro: %s", e)


def _interpretar_grau_por_texto(texto: str) -> Optional[str]:
    """Converte texto livre de grau para opção válida."""
    normalizado = _normalizar_texto(texto)
    aliases = {
        "aprendiz": "Aprendiz",
        "companheiro": "Companheiro",
        "mestre": "Mestre",
        "mestre instalado": "Mestre Instalado",
        "mi": "Mestre Instalado",
    }
    if normalizado in aliases:
        return aliases[normalizado]

    for grau in GRAUS_OPCOES:
        if _normalizar_texto(grau) == normalizado:
            return grau
    return None


def _interpretar_vm_por_texto(texto: str) -> Optional[str]:
    """Converte texto livre em Sim/Não para Venerável Mestre."""
    normalizado = _normalizar_texto(texto)
    if normalizado in {"sim", "s", "sou", "yes", "y"}:
        return VM_SIM
    if normalizado in {"nao", "n", "não", "no"}:
        return VM_NAO
    return None


# ============================================
# FUNÇÕES AUXILIARES DE INTERFACE
# ============================================

def _teclado_nav(estado_voltar: int) -> InlineKeyboardMarkup:
    """Cria teclado com botões Voltar e Cancelar."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{estado_voltar}"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar"),
            ]
        ]
    )


def _teclado_confirmar() -> InlineKeyboardMarkup:
    """Cria teclado para tela de confirmação."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirmar cadastro", callback_data="confirmar_cadastro")],
            [
                InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{POTENCIA}"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar"),
            ],
        ]
    )


def _teclado_inicio(
    cadastrado: bool,
    revalidacao: bool = False,
    cadastro_parcial: bool = False,
) -> InlineKeyboardMarkup:
    """Cria teclado da tela inicial de cadastro."""
    btn_webapp = (
        InlineKeyboardButton("🧾 Abrir formulário de cadastro", web_app=WebAppInfo(url=WEBAPP_URL_MEMBRO))
        if WEBAPP_URL_MEMBRO
        else None
    )
    linhas = []

    if btn_webapp:
        linhas.append([btn_webapp])

    if revalidacao:
        linhas.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])
        return InlineKeyboardMarkup(linhas)
    if cadastrado:
        linhas.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])
        return InlineKeyboardMarkup(linhas)
    if cadastro_parcial:
        linhas.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])
        return InlineKeyboardMarkup(linhas)

    linhas.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])
    return InlineKeyboardMarkup(linhas)


def _teclado_grau() -> InlineKeyboardMarkup:
    """Cria teclado com opções de grau."""
    botoes = [[InlineKeyboardButton(g, callback_data=f"set_grau|{g}")] for g in GRAUS_OPCOES]
    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{DATA_NASC}")])
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botoes)


def _teclado_vm() -> InlineKeyboardMarkup:
    """Cria teclado para pergunta de Venerável Mestre."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Sim", callback_data=f"set_vm|{VM_SIM}")],
            [InlineKeyboardButton("Não", callback_data=f"set_vm|{VM_NAO}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{GRAU}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )


async def _navegar_etapa(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    estado: int,
    retomada: bool = False,
) -> int:
    """Exibe a etapa solicitada com teclado e instruções apropriadas."""
    if estado == GRAU:
        await navegar_para(update, context, "Cadastro", _texto_etapa(GRAU, retomada=retomada), _teclado_grau())
        return GRAU
    if estado == VM:
        await navegar_para(update, context, "Cadastro", _texto_etapa(VM, retomada=retomada), _teclado_vm())
        return VM
    if estado == CONFIRMAR:
        await _mostrar_confirmacao(update, context)
        return CONFIRMAR

    await navegar_para(
        update,
        context,
        "Cadastro",
        _texto_etapa(estado, retomada=retomada),
        _teclado_nav(max(NOME, estado - 1)),
    )
    return estado


def _validar_data_nasc(texto: str) -> bool:
    """Valida se a data está no formato DD/MM/AAAA."""
    s = (texto or "").strip()
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        return False
    try:
        datetime.strptime(s, "%d/%m/%Y")
        return True
    except Exception:
        return False


def _validar_numero_loja(texto: str) -> bool:
    """Valida se o número da loja contém apenas dígitos."""
    s = (texto or "").strip()
    if s == "":
        return False
    return bool(re.fullmatch(r"\d+", s))


def _resumo_cadastro(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Gera resumo dos dados para confirmação."""
    nome = (context.user_data.get("cadastro_nome") or "").strip()
    data_nasc = (context.user_data.get("cadastro_data_nasc") or "").strip()
    grau = (context.user_data.get("cadastro_grau") or "").strip()
    vm = (context.user_data.get("cadastro_vm") or "").strip()
    loja = (context.user_data.get("cadastro_loja") or "").strip()
    numero_loja = (context.user_data.get("cadastro_numero_loja") or "").strip()
    oriente = (context.user_data.get("cadastro_oriente") or "").strip()
    potencia = (context.user_data.get("cadastro_potencia") or "").strip()

    numero_fmt = f" - Nº {numero_loja}" if numero_loja and numero_loja not in ("0", "") else ""

    return (
        "*Confira seus dados:*\n\n"
        f"👤 *Nome:* {nome}\n"
        f"🎂 *Nascimento:* {data_nasc}\n"
        f"🔺 *Grau:* {grau}\n"
        f"🔨 *Venerável Mestre:* {vm}\n"
        f"🏛 *Loja:* {loja}{numero_fmt}\n"
        f"📍 *Oriente:* {oriente}\n"
        f"⚜️ *Potência:* {potencia}\n\n"
        "_Seus dados serão mantidos em absoluto sigilo._"
    )


# ============================================
# FUNÇÃO PRINCIPAL DE ENTRADA
# ============================================

async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ponto de entrada para o cadastro.
    
    Fluxo:
    - Em grupo: orienta a usar o privado
    - Em privado: se cadastrado, oferece editar; se não, iniciar
    """
    try:
        # Se veio do grupo, orienta
        if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
            if update.message:
                await update.message.reply_text(
                    CADASTRO_REDIRECIONAR_PRIVADO
                )
            return

        # Aqui já é privado
        telegram_id = update.effective_user.id
        membro = buscar_membro(telegram_id)
        cadastrado = bool(membro)
        origem_grupo = bool(context.user_data.pop("origem_grupo_cadastro", False))
        forcar_revalidacao = bool(context.user_data.pop("forcar_revalidacao_cadastro", False))
        cadastro_parcial = (not cadastrado) and _cadastro_parcial_em_andamento(context)

        if forcar_revalidacao and cadastrado:
            texto = CADASTRO_REVALIDACAO_NECESSARIA
        elif cadastro_parcial:
            texto = CADASTRO_PARCIAL_EM_ANDAMENTO
        elif not cadastrado and origem_grupo:
            texto = CADASTRO_BOAS_VINDAS_GRUPO
        else:
            texto = CADASTRO_INICIO_PADRAO

        if not WEBAPP_URL_MEMBRO:
            texto = (
                "⚠️ O formulário de cadastro está temporariamente indisponível.\n\n"
                "Assim que o Mini App estiver online novamente, o cadastro continuará por ele."
            )

        teclado_inicio = _teclado_inicio(cadastrado, forcar_revalidacao, cadastro_parcial)

        if update.callback_query:
            await update.callback_query.edit_message_text(
                texto,
                parse_mode="Markdown",
                reply_markup=teclado_inicio
            )
        elif update.message:
            await update.message.reply_text(
                texto,
                parse_mode="Markdown",
                reply_markup=teclado_inicio
            )
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Erro em cadastro_start: {e}\n{traceback.format_exc()}")
        if update.message:
            await update.message.reply_text(ERRO_GENERICO)
        return ConversationHandler.END


# ============================================
# INICIAR / CONTINUAR / EDITAR
# ============================================

async def iniciar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia um novo cadastro."""
    query = update.callback_query
    await _responder_callback_seguro(query)

    # Preserva pos_cadastro (confirmação pendente)
    pos = context.user_data.get("pos_cadastro")
    context.user_data.clear()
    if pos:
        context.user_data["pos_cadastro"] = pos

    await navegar_para(
        update,
        context,
        "Cadastro",
        CADASTRO_NOVO_INTRO_TMPL.format(etapa_nome=_texto_etapa(NOME)),
        _teclado_nav(NOME),
    )
    return NOME


async def continuar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retoma cadastro parcial do ponto em que o usuário parou."""
    query = update.callback_query
    await _responder_callback_seguro(query)

    estado = _estado_pendente_cadastro(context)
    return await _navegar_etapa(update, context, estado, retomada=True)


async def editar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia edição de cadastro existente."""
    query = update.callback_query
    await _responder_callback_seguro(query)

    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    # Preserva pos_cadastro
    pos = context.user_data.get("pos_cadastro")
    context.user_data.clear()
    if pos:
        context.user_data["pos_cadastro"] = pos

    if not membro:
        teclado = (
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("🧾 Abrir formulário de cadastro", web_app=WebAppInfo(url=WEBAPP_URL_MEMBRO))]]
            )
            if WEBAPP_URL_MEMBRO
            else InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")]]
            )
        )
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "Você ainda não tem cadastro. Vamos iniciar agora.",
            teclado
        )
        return ConversationHandler.END

    # Pré-preenche com dados existentes
    context.user_data["cadastro_nome"] = (membro.get("Nome") or membro.get("nome") or "").strip()
    context.user_data["cadastro_data_nasc"] = (membro.get("Data de nascimento") or membro.get("data_nasc") or "").strip()
    context.user_data["cadastro_grau"] = (membro.get("Grau") or membro.get("grau") or "").strip()
    context.user_data["cadastro_vm"] = (membro.get("Venerável Mestre") or membro.get("veneravel_mestre") or membro.get("vm") or "").strip()
    context.user_data["cadastro_loja"] = (membro.get("Loja") or membro.get("loja") or "").strip()
    context.user_data["cadastro_numero_loja"] = (membro.get("Número da loja") or membro.get("numero_loja") or "").strip()
    context.user_data["cadastro_oriente"] = (membro.get("Oriente") or membro.get("oriente") or "").strip()
    context.user_data["cadastro_potencia"] = (membro.get("Potência") or membro.get("potencia") or "").strip()

    await navegar_para(
        update, context,
        "Editar Cadastro",
        CADASTRO_REVALIDAR_INTRO_TMPL.format(etapa_nome=_texto_etapa(NOME)),
        _teclado_nav(NOME)
    )
    return NOME


# ============================================
# RECEBIMENTO DE DADOS (TEXTO)
# ============================================

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe e valida o nome."""
    nome = (update.message.text or "").strip()
    if len(nome) < 3:
        await update.message.reply_text(
            CADASTRO_ERRO_NOME_CURTO,
            parse_mode="Markdown",
        )
        return NOME

    context.user_data["cadastro_nome"] = nome
    return await _navegar_etapa(update, context, DATA_NASC)


async def receber_data_nasc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe e valida a data de nascimento."""
    texto = (update.message.text or "").strip()
    if not _validar_data_nasc(texto):
        await update.message.reply_text(
            CADASTRO_ERRO_DATA_NASC,
            parse_mode="Markdown",
        )
        return DATA_NASC

    context.user_data["cadastro_data_nasc"] = texto
    return await _navegar_etapa(update, context, GRAU)


async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o nome da loja."""
    loja = (update.message.text or "").strip()
    if len(loja) < 2:
        await update.message.reply_text(CADASTRO_ERRO_LOJA, parse_mode="Markdown")
        return LOJA

    context.user_data["cadastro_loja"] = loja
    return await _navegar_etapa(update, context, NUMERO_LOJA)


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o número da loja."""
    numero = (update.message.text or "").strip()
    if not _validar_numero_loja(numero):
        await update.message.reply_text(CADASTRO_ERRO_NUMERO_LOJA)
        return NUMERO_LOJA

    context.user_data["cadastro_numero_loja"] = numero
    return await _navegar_etapa(update, context, ORIENTE)


async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o oriente."""
    oriente = (update.message.text or "").strip()
    if len(oriente) < 2:
        await update.message.reply_text(CADASTRO_ERRO_ORIENTE, parse_mode="Markdown")
        return ORIENTE

    context.user_data["cadastro_oriente"] = oriente
    return await _navegar_etapa(update, context, POTENCIA)


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a potência."""
    potencia = (update.message.text or "").strip()
    if len(potencia) < 2:
        await update.message.reply_text(CADASTRO_ERRO_POTENCIA, parse_mode="Markdown")
        return POTENCIA

    context.user_data["cadastro_potencia"] = potencia
    return await _navegar_etapa(update, context, CONFIRMAR)


# ============================================
# SETTERS (BOTÕES)
# ============================================

async def receber_grau_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Aceita grau digitado em texto livre como alternativa aos botões."""
    grau = _interpretar_grau_por_texto(update.message.text or "")
    if not grau:
        await navegar_para(
            update,
            context,
            "Cadastro",
            CADASTRO_ERRO_GRAU_TEXTO,
            _teclado_grau(),
        )
        return GRAU

    context.user_data["cadastro_grau"] = grau
    return await _navegar_etapa(update, context, VM)


async def receber_vm_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Aceita Sim/Não em texto livre para Venerável Mestre."""
    vm = _interpretar_vm_por_texto(update.message.text or "")
    if vm is None:
        await navegar_para(
            update,
            context,
            "Cadastro",
            CADASTRO_ERRO_VM_TEXTO,
            _teclado_vm(),
        )
        return VM

    context.user_data["cadastro_vm"] = vm
    return await _navegar_etapa(update, context, LOJA)

async def set_grau_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Define o grau selecionado via botão."""
    query = update.callback_query
    await _responder_callback_seguro(query)

    try:
        _, grau = query.data.split("|", 1)
    except Exception:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            CADASTRO_ERRO_GRAU_INVALIDO,
            _teclado_grau()
        )
        return GRAU

    if grau not in GRAUS_OPCOES:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            CADASTRO_ERRO_GRAU_SELECIONE,
            _teclado_grau()
        )
        return GRAU

    context.user_data["cadastro_grau"] = grau
    return await _navegar_etapa(update, context, VM)


async def set_vm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Define se é Venerável Mestre via botão."""
    query = update.callback_query
    await _responder_callback_seguro(query)

    try:
        _, vm = query.data.split("|", 1)
    except Exception:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            CADASTRO_ERRO_VM_INVALIDO,
            _teclado_vm()
        )
        return VM

    if vm not in (VM_SIM, VM_NAO):
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            CADASTRO_ERRO_VM_INVALIDO,
            _teclado_vm()
        )
        return VM

    context.user_data["cadastro_vm"] = vm
    return await _navegar_etapa(update, context, LOJA)


# ============================================
# CONFIRMAÇÃO FINAL
# ============================================

async def _mostrar_confirmacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe tela de confirmação com resumo dos dados."""
    texto = CADASTRO_REVISAO_FINAL_TMPL.format(resumo=_resumo_cadastro(context))
    await navegar_para(update, context, "Confirmar Cadastro", texto, _teclado_confirmar())


def _dados_para_salvar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    """Monta payload final do cadastro para persistência."""
    return {
        "nome": context.user_data.get("cadastro_nome", ""),
        "data_nasc": context.user_data.get("cadastro_data_nasc", ""),
        "grau": context.user_data.get("cadastro_grau", ""),
        "loja": context.user_data.get("cadastro_loja", ""),
        "numero_loja": context.user_data.get("cadastro_numero_loja", ""),
        "oriente": context.user_data.get("cadastro_oriente", ""),
        "potencia": context.user_data.get("cadastro_potencia", ""),
        "telegram_id": update.effective_user.id,
        "veneravel_mestre": context.user_data.get("cadastro_vm", ""),
    }


async def _finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Valida pendências e persiste cadastro com tratamento de falha."""
    estado_pendente = _estado_pendente_cadastro(context)
    if estado_pendente != CONFIRMAR:
        await _enviar_ou_editar_mensagem(
            context,
            update.effective_user.id,
            TIPO_RESULTADO,
            CADASTRO_DADOS_PENDENTES,
        )
        return await _navegar_etapa(update, context, estado_pendente, retomada=True)

    dados_membro = _dados_para_salvar(update, context)
    salvo = cadastrar_membro(dados_membro)
    if not salvo:
        logger.error("Falha ao persistir cadastro do usuário %s", update.effective_user.id)
        await _enviar_ou_editar_mensagem(
            context,
            update.effective_user.id,
            TIPO_RESULTADO,
            CADASTRO_FALHA_SALVAR,
            _teclado_confirmar(),
        )
        return CONFIRMAR

    # Preserva pos_cadastro
    pos = context.user_data.get("pos_cadastro")
    context.user_data.clear()
    if pos:
        context.user_data["pos_cadastro"] = pos

    await navegar_para(
        update,
        context,
        "Cadastro Concluído",
        CADASTRO_CONCLUIDO,
        InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")]]
        ),
    )

    # Executa ação pós-cadastro se existir (após a confirmação para não sobrescrevê-la)
    if pos and isinstance(pos, dict) and pos.get("acao") == "confirmar":
        try:
            from src.eventos import iniciar_confirmacao_presenca_pos_cadastro
            await iniciar_confirmacao_presenca_pos_cadastro(update, context, pos)
            context.user_data.pop("pos_cadastro", None)
        except Exception as e:
            logger.error(f"Erro no pos_cadastro: {e}\n{traceback.format_exc()}")

    return ConversationHandler.END


async def receber_confirmacao_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite confirmar por texto em vez de botão para reduzir atrito."""
    texto = _normalizar_texto(update.message.text or "")
    if texto in {"confirmar", "confirmo", "ok", "sim"}:
        return await _finalizar_cadastro(update, context)

    await update.message.reply_text(
        CADASTRO_PROMPT_CONFIRMAR,
        parse_mode="Markdown",
    )
    await _mostrar_confirmacao(update, context)
    return CONFIRMAR


async def confirmar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e salva o cadastro."""
    query = update.callback_query
    await _responder_callback_seguro(query)

    try:
        return await _finalizar_cadastro(update, context)

    except Exception as e:
        logger.error(f"Erro em confirmar_cadastro: {e}\n{traceback.format_exc()}")
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            ERRO_GENERICO
        )
        return ConversationHandler.END


# ============================================
# NAVEGAÇÃO (VOLTAR / CANCELAR)
# ============================================

async def navegacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa comandos de navegação (voltar/cancelar)."""
    query = update.callback_query
    await _responder_callback_seguro(query)

    data = query.data or ""

    if data == "cancelar":
        return await cancelar_cadastro(update, context)

    if data.startswith("voltar|"):
        try:
            _, estado_str = data.split("|", 1)
            estado = int(estado_str)
        except Exception:
            estado = NOME

        estado = max(NOME, min(CONFIRMAR, estado))
        return await _navegar_etapa(update, context, estado)

    return NOME


async def cancelar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de cadastro."""
    try:
        if update.callback_query:
            await _responder_callback_seguro(update.callback_query)
            await navegar_para(
                update, context,
                "Cadastro",
                CADASTRO_OPERACAO_CANCELADA,
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")
                ]])
            )
        elif update.message:
            await update.message.reply_text(CADASTRO_CANCELADO)
    except Exception as e:
        logger.error(f"Erro em cancelar_cadastro: {e}\n{traceback.format_exc()}")

    # Limpa dados, preservando pos_cadastro
    pos = context.user_data.get("pos_cadastro")
    context.user_data.clear()
    if pos:
        context.user_data["pos_cadastro"] = pos
        
    return ConversationHandler.END


# ============================================
# CONVERSATION HANDLER
# ============================================

cadastro_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(iniciar_cadastro_callback, pattern=r"^iniciar_cadastro$"),
        CallbackQueryHandler(continuar_cadastro_callback, pattern=r"^continuar_cadastro$"),
        CallbackQueryHandler(editar_cadastro_callback, pattern=r"^editar_cadastro$"),
    ],
    states={
        NOME: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_nome),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        DATA_NASC: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_data_nasc),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        GRAU: [
            CallbackQueryHandler(set_grau_callback, pattern=r"^set_grau\|"),
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_grau_texto),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        VM: [
            CallbackQueryHandler(set_vm_callback, pattern=r"^set_vm\|"),
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_vm_texto),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_loja),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        NUMERO_LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_numero_loja),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        ORIENTE: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_oriente),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        POTENCIA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_potencia),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_cadastro, pattern=r"^confirmar_cadastro$"),
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_confirmacao_texto),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_cadastro),
        CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
    ],
    allow_reentry=True,
    name="cadastro_handler",
    persistent=False,
)
