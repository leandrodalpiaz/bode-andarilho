# src/cadastro_evento.py
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

from src.sheets import cadastrar_evento, listar_eventos, listar_lojas
from src.permissoes import get_nivel


# =========================
# Config
# =========================
GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID", "-1003721338228")
MAX_TEXTO = 250

# =========================
# Estados
# =========================
(
    ESCOLHER_LOJA,
    DATA,
    HORARIO,
    NOME_LOJA,
    NUMERO_LOJA,
    ORIENTE,
    GRAU,
    TIPO_SESSAO,
    RITO,
    POTENCIA,
    TRAJE,
    AGAPE,
    AGAPE_TIPO,
    OBSERVACOES_TEM,
    OBSERVACOES_TEXTO,
    ENDERECO,
    CONFIRMAR,
) = range(17)

# =========================
# Opções fixas
# =========================
GRAUS_OPCOES = [
    ("Aprendiz", "Aprendiz"),
    ("Companheiro", "Companheiro"),
    ("Mestre", "Mestre"),
    ("Mestre Instalado", "Mestre Instalado"),
]

AGAPE_RESPOSTAS = [("Sim", "sim"), ("Não", "nao")]
AGAPE_TIPOS = [("Gratuito", "gratuito"), ("Pago (dividido)", "pago")]
OBS_RESPOSTAS = [("Sim", "sim"), ("Não", "nao")]


# =========================
# Helpers
# =========================
def _norm_text(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _truncate(s: str, n: int = MAX_TEXTO) -> str:
    s = _norm_text(s)
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _escape_md(s: str) -> str:
    """
    Escapa Markdown V1 (parse_mode="Markdown") para não quebrar formatação.
    """
    s = _norm_text(s)
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def _parse_data_ddmmyyyy(texto: str) -> Optional[datetime]:
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y")
    except Exception:
        return None


def _parse_hora(texto: str) -> Optional[str]:
    """
    Aceita HH:MM ou HH:MM:SS e devolve HH:MM.
    """
    t = _norm_text(texto)
    if not t:
        return None

    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", t)
    if not m:
        return None

    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None

    return f"{hh:02d}:{mm:02d}"


def _dia_semana_ingles(dt: datetime) -> str:
    # Mantém compatibilidade com sua planilha (Monday, Tuesday...)
    return dt.strftime("%A")


def _teclado_cancelar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")]])


def _teclado_voltar_cancelar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")],
        ]
    )


def _teclado_sim_nao(prefix: str) -> InlineKeyboardMarkup:
    opcoes = AGAPE_RESPOSTAS if prefix == "agape" else OBS_RESPOSTAS
    linhas = [[InlineKeyboardButton(lbl, callback_data=f"{prefix}|{val}")] for (lbl, val) in opcoes]
    linhas.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_graus() -> InlineKeyboardMarkup:
    linhas = [[InlineKeyboardButton(lbl, callback_data=f"grau|{val}")] for (lbl, val) in GRAUS_OPCOES]
    linhas.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_agape_tipos() -> InlineKeyboardMarkup:
    linhas = [[InlineKeyboardButton(lbl, callback_data=f"agape_tipo|{val}")] for (lbl, val) in AGAPE_TIPOS]
    linhas.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
    return InlineKeyboardMarkup(linhas)


async def _safe_edit(query, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, parse_mode: Optional[str] = None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


def _event_key(data: str, hora: str, nome: str, numero: str) -> str:
    return f"{_norm_text(data)}|{_norm_text(hora)}|{_norm_text(nome).lower()}|{_norm_text(numero)}"


def _status_ativo_ou_vazio(status: str) -> bool:
    s = _norm_text(status).lower()
    return s == "" or s == "ativo"


def _encontrar_duplicado(evento: Dict[str, Any], eventos_existentes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    alvo = _event_key(
        evento.get("Data do evento", ""),
        evento.get("Hora", ""),
        evento.get("Nome da loja", ""),
        evento.get("Número da loja", ""),
    )

    for ev in eventos_existentes:
        if not _status_ativo_ou_vazio(ev.get("Status", "")):
            continue
        k = _event_key(
            ev.get("Data do evento", ""),
            ev.get("Hora", ""),
            ev.get("Nome da loja", ""),
            ev.get("Número da loja", ""),
        )
        if k == alvo:
            return ev
    return None


def _montar_evento_dict(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    data_txt = context.user_data.get("novo_evento_data", "")
    hora_txt = context.user_data.get("novo_evento_horario", "")

    dt = _parse_data_ddmmyyyy(data_txt)
    dia_semana = _dia_semana_ingles(dt) if dt else ""

    agape_sim = context.user_data.get("novo_evento_agape", "nao")
    agape_tipo = context.user_data.get("novo_evento_agape_tipo", "")

    agape_str = ""
    if agape_sim == "sim":
        if agape_tipo == "gratuito":
            agape_str = "Sim (Gratuito)"
        elif agape_tipo == "pago":
            agape_str = "Sim (Pago)"
        else:
            agape_str = "Sim"
    else:
        agape_str = "Não"

    obs_txt = context.user_data.get("novo_evento_observacoes_texto", "")
    if context.user_data.get("novo_evento_observacoes_tem", "nao") != "sim":
        obs_txt = ""

    return {
        "Data do evento": data_txt,
        "Dia da semana": dia_semana,
        "Hora": hora_txt,
        "Nome da loja": context.user_data.get("novo_evento_nome_loja", ""),
        "Número da loja": context.user_data.get("novo_evento_numero_loja", ""),
        "Oriente": context.user_data.get("novo_evento_oriente", ""),
        "Grau": context.user_data.get("novo_evento_grau", ""),
        "Tipo de sessão": context.user_data.get("novo_evento_tipo_sessao", ""),
        "Rito": context.user_data.get("novo_evento_rito", ""),
        "Potência": context.user_data.get("novo_evento_potencia", ""),
        "Traje obrigatório": context.user_data.get("novo_evento_traje", ""),
        "Ágape": agape_str,
        "Observações": obs_txt,
        "Telegram ID do grupo": context.user_data.get("novo_evento_telegram_id_grupo", GRUPO_PRINCIPAL_ID),
        "Telegram ID do secretário": context.user_data.get("novo_evento_telegram_id_secretario", ""),
        "Status": "Ativo",
        "Endereço da sessão": context.user_data.get("novo_evento_endereco", ""),
    }


def _limpar_contexto_evento(context: ContextTypes.DEFAULT_TYPE):
    for k in list(context.user_data.keys()):
        if k.startswith("novo_evento_"):
            context.user_data.pop(k, None)
    context.user_data.pop("lojas_disponiveis", None)


def _voltar_um_passo(context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Remove o último campo preenchido (ordem do fluxo) e devolve o estado anterior.
    """
    # Ordem exata do fluxo
    ordem = [
        ("novo_evento_data", DATA),
        ("novo_evento_horario", HORARIO),
        ("novo_evento_nome_loja", NOME_LOJA),
        ("novo_evento_numero_loja", NUMERO_LOJA),
        ("novo_evento_oriente", ORIENTE),
        ("novo_evento_grau", GRAU),
        ("novo_evento_tipo_sessao", TIPO_SESSAO),
        ("novo_evento_rito", RITO),
        ("novo_evento_potencia", POTENCIA),
        ("novo_evento_traje", TRAJE),
        ("novo_evento_agape", AGAPE),
        ("novo_evento_agape_tipo", AGAPE_TIPO),
        ("novo_evento_observacoes_tem", OBSERVACOES_TEM),
        ("novo_evento_observacoes_texto", OBSERVACOES_TEXTO),
        ("novo_evento_endereco", ENDERECO),
    ]

    # Remove primeiro o que for "mais ao fim" e estiver preenchido,
    # respeitando os ramos (agape_tipo só se agape==sim; obs_texto só se obs_tem==sim).
    for key, state in reversed(ordem):
        if key not in context.user_data:
            continue

        if key == "novo_evento_agape_tipo" and context.user_data.get("novo_evento_agape") != "sim":
            context.user_data.pop(key, None)
            continue

        if key == "novo_evento_observacoes_texto" and context.user_data.get("novo_evento_observacoes_tem") != "sim":
            context.user_data.pop(key, None)
            continue

        context.user_data.pop(key, None)
        return state

    return DATA


async def _ir_proximo_passo_por_callback(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Decide qual a próxima pergunta com base nos campos já preenchidos.
    (Usado no "Voltar" e após selecionar botões.)
    """
    if "novo_evento_data" not in context.user_data:
        await _safe_edit(query, "Qual a *Data do evento*? (Ex: 25/03/2026)", parse_mode="Markdown", reply_markup=_teclado_cancelar())
        return DATA

    if "novo_evento_horario" not in context.user_data:
        await _safe_edit(query, "Qual o *Horário*? (Ex: 19:30)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return HORARIO

    if "novo_evento_nome_loja" not in context.user_data:
        await _safe_edit(query, "Qual o *Nome da loja*?", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return NOME_LOJA

    if "novo_evento_numero_loja" not in context.user_data:
        await _safe_edit(query, "Qual o *Número da loja*? (Ex: 123) (se não houver, digite 0)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return NUMERO_LOJA

    if "novo_evento_oriente" not in context.user_data:
        await _safe_edit(query, "Qual o *Oriente*?", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return ORIENTE

    if "novo_evento_grau" not in context.user_data:
        await _safe_edit(query, "Qual o *Grau mínimo*?", parse_mode="Markdown", reply_markup=_teclado_graus())
        return GRAU

    if "novo_evento_tipo_sessao" not in context.user_data:
        await _safe_edit(query, "Qual o *Tipo de sessão*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return TIPO_SESSAO

    if "novo_evento_rito" not in context.user_data:
        await _safe_edit(query, "Qual o *Rito*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return RITO

    if "novo_evento_potencia" not in context.user_data:
        await _safe_edit(query, "Qual a *Potência*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return POTENCIA

    if "novo_evento_traje" not in context.user_data:
        await _safe_edit(query, "Qual o *Traje obrigatório*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return TRAJE

    if "novo_evento_agape" not in context.user_data:
        await _safe_edit(query, "Haverá *Ágape*?", parse_mode="Markdown", reply_markup=_teclado_sim_nao("agape"))
        return AGAPE

    if context.user_data.get("novo_evento_agape") == "sim" and "novo_evento_agape_tipo" not in context.user_data:
        await _safe_edit(query, "Qual o tipo de Ágape?", reply_markup=_teclado_agape_tipos())
        return AGAPE_TIPO

    if "novo_evento_observacoes_tem" not in context.user_data:
        await _safe_edit(query, "Deseja adicionar *observações*?", parse_mode="Markdown", reply_markup=_teclado_sim_nao("obs"))
        return OBSERVACOES_TEM

    if context.user_data.get("novo_evento_observacoes_tem") == "sim" and "novo_evento_observacoes_texto" not in context.user_data:
        await _safe_edit(query, "Digite as *observações* (texto livre):", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return OBSERVACOES_TEXTO

    if "novo_evento_endereco" not in context.user_data:
        await _safe_edit(query, "Agora informe o *Endereço da sessão*:", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return ENDERECO

    # Se chegou aqui, vai para a confirmação
    evento = _montar_evento_dict(context)
    eventos_existentes = listar_eventos() or []
    dup = _encontrar_duplicado(evento, eventos_existentes)

    texto = _montar_resumo_evento_md(evento, duplicado=dup)
    teclado = _teclado_confirmacao(tem_duplicado=dup is not None)
    await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=teclado)
    return CONFIRMAR


def _montar_resumo_evento_md(evento: Dict[str, Any], duplicado: Optional[Dict[str, Any]] = None) -> str:
    nome = _escape_md(evento.get("Nome da loja", ""))
    numero = _escape_md(evento.get("Número da loja", ""))
    numero_fmt = f" {numero}" if numero and numero != "0" else ""
    data_txt = _escape_md(evento.get("Data do evento", ""))
    hora_txt = _escape_md(evento.get("Hora", ""))
    oriente = _escape_md(evento.get("Oriente", ""))
    grau = _escape_md(evento.get("Grau", ""))
    tipo = _escape_md(evento.get("Tipo de sessão", ""))
    rito = _escape_md(evento.get("Rito", ""))
    potencia = _escape_md(evento.get("Potência", ""))
    traje = _escape_md(evento.get("Traje obrigatório", ""))
    agape = _escape_md(evento.get("Ágape", ""))
    obs = _escape_md(evento.get("Observações", ""))
    end = _escape_md(evento.get("Endereço da sessão", ""))

    linhas = [
        "*Confirme os dados do evento:*",
        "",
        f"🏛 *Loja:* {nome}{numero_fmt}",
        f"📅 *Data:* {data_txt}",
        f"🕕 *Hora:* {hora_txt}",
        f"📍 *Oriente:* {oriente}",
        f"🔺 *Grau mínimo:* {grau}",
        f"🕯 *Tipo de sessão:* {tipo}",
        f"📜 *Rito:* {rito}",
        f"⚜️ *Potência:* {potencia}",
        f"🎩 *Traje:* {traje}",
        f"🍽 *Ágape:* {agape}",
        f"🗺 *Endereço:* {end}",
    ]
    if obs:
        linhas.append(f"📝 *Observações:* {obs}")

    if duplicado:
        d_nome = _escape_md(duplicado.get("Nome da loja", ""))
        d_num = _escape_md(duplicado.get("Número da loja", ""))
        d_num_fmt = f" {d_num}" if d_num and d_num != "0" else ""
        d_data = _escape_md(duplicado.get("Data do evento", ""))
        d_hora = _escape_md(duplicado.get("Hora", ""))
        linhas.extend(
            [
                "",
                "⚠️ *Atenção:* encontrei um evento ativo com a mesma *data/hora/loja/número*:",
                f"• {d_nome}{d_num_fmt} — {d_data} {d_hora}",
            ]
        )

    return "\n".join(linhas)


def _teclado_confirmacao(tem_duplicado: bool) -> InlineKeyboardMarkup:
    linhas = []
    if tem_duplicado:
        linhas.append([InlineKeyboardButton("⚠️ Publicar mesmo assim", callback_data="confirmar_publicacao_forcar")])
    linhas.append([InlineKeyboardButton("✅ Confirmar publicação", callback_data="confirmar_publicacao")])
    linhas.append([InlineKeyboardButton("🔄 Refazer", callback_data="refazer_cadastro")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_publicacao")])
    return InlineKeyboardMarkup(linhas)


def _teclado_pos_publicacao(id_evento: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento}|sem")],
            [InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento}")],
        ]
    )


# =========================
# Início
# =========================
async def novo_evento_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🏛 Iniciando cadastro de evento...")

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    if nivel not in ["2", "3"]:
        await _safe_edit(query, "Você não tem permissão para cadastrar eventos.")
        return ConversationHandler.END

    # Armazena o ID do usuário que está cadastrando
    context.user_data["novo_evento_telegram_id_secretario"] = str(user_id)

    # Se veio do grupo, bloqueia e orienta
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        context.user_data["novo_evento_telegram_id_grupo"] = str(update.effective_chat.id)
        await _safe_edit(
            query,
            "🔔 O cadastro de eventos deve ser feito no meu chat privado.\n\n"
            "Acesse meu privado e utilize o menu 'Área do Secretário' para cadastrar.",
        )
        return ConversationHandler.END

    # Privado: define grupo principal automaticamente
    context.user_data["novo_evento_telegram_id_grupo"] = GRUPO_PRINCIPAL_ID

    # Limpa restos de cadastro anterior
    for k in list(context.user_data.keys()):
        if k.startswith("novo_evento_") and k not in ("novo_evento_telegram_id_grupo", "novo_evento_telegram_id_secretario"):
            context.user_data.pop(k, None)

    # Verifica se o secretário tem lojas cadastradas
    lojas = listar_lojas(user_id)
    
    if lojas:
        # Oferece opção de usar uma loja cadastrada
        botoes_lojas = []
        for i, loja in enumerate(lojas[:5]):  # Limite de 5 lojas para não estourar
            nome = loja.get("Nome da Loja", "")
            numero = loja.get("Número", "")
            nome_fmt = f"{nome} {numero}" if numero else nome
            botoes_lojas.append([
                InlineKeyboardButton(
                    f"🏛 {nome_fmt}",
                    callback_data=f"usar_loja_{i}"
                )
            ])
        
        botoes_lojas.append([InlineKeyboardButton("➕ Cadastrar manualmente", callback_data="cadastrar_manual")])
        botoes_lojas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
        
        # Guarda as lojas no context para usar depois
        context.user_data["lojas_disponiveis"] = lojas
        
        await _safe_edit(
            query,
            "🏛️ *Cadastro de Evento*\n\n"
            "Você tem lojas cadastradas. Deseja usar os dados de alguma como atalho?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes_lojas),
        )
        return ESCOLHER_LOJA
    else:
        # Segue fluxo normal
        await _safe_edit(
            query,
            "Certo, vamos cadastrar um novo evento.\n\nQual a *Data do evento*? (Ex: 25/03/2026)",
            parse_mode="Markdown",
            reply_markup=_teclado_cancelar(),
        )
        return DATA


async def escolher_loja_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa a escolha da loja pelo secretário."""
    query = update.callback_query
    await query.answer("🏛 Carregando dados da loja...")

    data = query.data
    if data == "cadastrar_manual":
        # Segue fluxo normal
        await _safe_edit(
            query,
            "Certo, vamos cadastrar um novo evento.\n\nQual a *Data do evento*? (Ex: 25/03/2026)",
            parse_mode="Markdown",
            reply_markup=_teclado_cancelar(),
        )
        return DATA
    
    if data.startswith("usar_loja_"):
        try:
            index = int(data.split("_")[2])
            lojas = context.user_data.get("lojas_disponiveis", [])
            
            if 0 <= index < len(lojas):
                loja = lojas[index]
                # Pré-preenche os dados da loja
                context.user_data["novo_evento_nome_loja"] = loja.get("Nome da Loja", "")
                context.user_data["novo_evento_numero_loja"] = str(loja.get("Número", "0"))
                context.user_data["novo_evento_rito"] = loja.get("Rito", "")
                context.user_data["novo_evento_potencia"] = loja.get("Potência", "")
                context.user_data["novo_evento_endereco"] = loja.get("Endereço", "")
                
                # Pula para a próxima pergunta não preenchida
                await _safe_edit(
                    query,
                    "✅ Dados da loja carregados!\n\n"
                    "Agora vamos preencher os detalhes da sessão.\n\n"
                    "Qual a *Data do evento*? (Ex: 25/03/2026)",
                    parse_mode="Markdown",
                    reply_markup=_teclado_voltar_cancelar(),
                )
                return DATA
            else:
                await _safe_edit(query, "❌ Loja não encontrada. Tente novamente.")
                return ESCOLHER_LOJA
        except (ValueError, IndexError):
            await _safe_edit(query, "❌ Erro ao processar seleção. Tente novamente.")
            return ESCOLHER_LOJA
    
    # Fallback
    return ESCOLHER_LOJA


# =========================
# Recebedores (texto)
# =========================
async def receber_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_text = _norm_text(update.message.text)
    dt = _parse_data_ddmmyyyy(data_text)
    if not dt:
        await update.message.reply_text("Data inválida. Use o formato *dd/mm/aaaa* (Ex: 25/03/2026).", parse_mode="Markdown")
        return DATA

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if dt < hoje:
        await update.message.reply_text("A data não pode ser no passado. Tente novamente:", parse_mode="Markdown")
        return DATA

    context.user_data["novo_evento_data"] = dt.strftime("%d/%m/%Y")
    await update.message.reply_text("Qual o *Horário*? (Ex: 19:30)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return HORARIO


async def receber_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hora = _parse_hora(update.message.text)
    if not hora:
        await update.message.reply_text("Horário inválido. Use *HH:MM* (Ex: 19:30).", parse_mode="Markdown")
        return HORARIO

    context.user_data["novo_evento_horario"] = hora
    await update.message.reply_text("Qual o *Nome da loja*?", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return NOME_LOJA


async def receber_nome_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = _truncate(update.message.text)
    if not nome:
        await update.message.reply_text("Informe um nome válido para a loja.", parse_mode="Markdown")
        return NOME_LOJA

    context.user_data["novo_evento_nome_loja"] = nome
    await update.message.reply_text("Qual o *Número da loja*? (se não houver, digite 0)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return NUMERO_LOJA


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    numero = _norm_text(update.message.text)

    # mantém comportamento permissivo: aceita "0" e números; se mandar qualquer coisa, salva como texto truncado
    numero = _truncate(numero, 30)
    if not numero:
        numero = "0"

    context.user_data["novo_evento_numero_loja"] = numero
    await update.message.reply_text("Qual o *Oriente*?", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return ORIENTE


async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    oriente = _truncate(update.message.text)
    if not oriente:
        await update.message.reply_text("Informe um oriente válido.", parse_mode="Markdown")
        return ORIENTE

    context.user_data["novo_evento_oriente"] = oriente
    await update.message.reply_text("Qual o *Grau mínimo*?", parse_mode="Markdown", reply_markup=_teclado_graus())
    return GRAU


# =========================
# Recebedor de Grau (BOTÕES)
# =========================
async def receber_grau_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔺 Selecionando grau...")

    _, grau = query.data.split("|", 1)
    grau = _norm_text(grau)

    # garante que só entra valor permitido
    permitidos = {v for _, v in GRAUS_OPCOES}
    if grau not in permitidos:
        await _safe_edit(query, "Grau inválido. Selecione uma opção:", parse_mode="Markdown", reply_markup=_teclado_graus())
        return GRAU

    context.user_data["novo_evento_grau"] = grau

    await _safe_edit(query, "Qual o *Tipo de sessão*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return TIPO_SESSAO


async def receber_tipo_sessao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = _truncate(update.message.text)
    context.user_data["novo_evento_tipo_sessao"] = val
    await update.message.reply_text("Qual o *Rito*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return RITO


async def receber_rito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = _truncate(update.message.text)
    context.user_data["novo_evento_rito"] = val
    await update.message.reply_text("Qual a *Potência*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = _truncate(update.message.text)
    context.user_data["novo_evento_potencia"] = val
    await update.message.reply_text("Qual o *Traje obrigatório*? (texto livre)", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return TRAJE


async def receber_traje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = _truncate(update.message.text)
    context.user_data["novo_evento_traje"] = val
    await update.message.reply_text("Haverá *Ágape*?", parse_mode="Markdown", reply_markup=_teclado_sim_nao("agape"))
    return AGAPE


# =========================
# Fluxos por botões
# =========================
async def receber_agape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🍽 Processando...")
    _, val = query.data.split("|", 1)
    val = _norm_text(val)

    if val not in ("sim", "nao"):
        await _safe_edit(query, "Selecione uma opção:", parse_mode="Markdown", reply_markup=_teclado_sim_nao("agape"))
        return AGAPE

    context.user_data["novo_evento_agape"] = val
    context.user_data.pop("novo_evento_agape_tipo", None)

    if val == "sim":
        await _safe_edit(query, "Qual o tipo de Ágape?", reply_markup=_teclado_agape_tipos())
        return AGAPE_TIPO

    await _safe_edit(query, "Deseja adicionar *observações*?", parse_mode="Markdown", reply_markup=_teclado_sim_nao("obs"))
    return OBSERVACOES_TEM


async def receber_agape_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🍽 Processando...")
    _, val = query.data.split("|", 1)
    val = _norm_text(val)

    if val not in ("gratuito", "pago"):
        await _safe_edit(query, "Selecione uma opção:", reply_markup=_teclado_agape_tipos())
        return AGAPE_TIPO

    context.user_data["novo_evento_agape_tipo"] = val
    await _safe_edit(query, "Deseja adicionar *observações*?", parse_mode="Markdown", reply_markup=_teclado_sim_nao("obs"))
    return OBSERVACOES_TEM


async def receber_observacoes_tem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("📝 Processando...")
    _, val = query.data.split("|", 1)
    val = _norm_text(val)

    if val not in ("sim", "nao"):
        await _safe_edit(query, "Selecione uma opção:", parse_mode="Markdown", reply_markup=_teclado_sim_nao("obs"))
        return OBSERVACOES_TEM

    context.user_data["novo_evento_observacoes_tem"] = val
    context.user_data.pop("novo_evento_observacoes_texto", None)

    if val == "sim":
        await _safe_edit(query, "Digite as *observações* (texto livre):", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
        return OBSERVACOES_TEXTO

    await _safe_edit(query, "Agora informe o *Endereço da sessão*:", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return ENDERECO


async def receber_observacoes_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = _truncate(update.message.text, 500)
    context.user_data["novo_evento_observacoes_texto"] = val
    await update.message.reply_text("Agora informe o *Endereço da sessão*:", parse_mode="Markdown", reply_markup=_teclado_voltar_cancelar())
    return ENDERECO


async def receber_endereco(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = _truncate(update.message.text, 400)
    context.user_data["novo_evento_endereco"] = val

    evento = _montar_evento_dict(context)
    eventos_existentes = listar_eventos() or []
    dup = _encontrar_duplicado(evento, eventos_existentes)

    await update.message.reply_text(
        _montar_resumo_evento_md(evento, duplicado=dup),
        parse_mode="Markdown",
        reply_markup=_teclado_confirmacao(tem_duplicado=dup is not None),
    )
    return CONFIRMAR


# =========================
# Confirmação / Publicação
# =========================
async def confirmar_publicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Publicando evento...")

    evento = _montar_evento_dict(context)
    eventos_existentes = listar_eventos() or []
    dup = _encontrar_duplicado(evento, eventos_existentes)
    if dup:
        texto = _montar_resumo_evento_md(evento, duplicado=dup) + "\n\n⚠️ Existe duplicidade. Use *Publicar mesmo assim* se quiser."
        await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=_teclado_confirmacao(tem_duplicado=True))
        return CONFIRMAR

    await _publicar_e_finalizar(query, context, evento)
    return ConversationHandler.END


async def confirmar_publicacao_forcar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⚠️ Publicando mesmo com duplicidade...")

    evento = _montar_evento_dict(context)
    await _publicar_e_finalizar(query, context, evento, forcar=True)
    return ConversationHandler.END


async def _publicar_e_finalizar(query, context: ContextTypes.DEFAULT_TYPE, evento: Dict[str, Any], forcar: bool = False):
    # 1) Salva no Sheets
    try:
        resultado = cadastrar_evento(evento)
    except Exception as e:
        await _safe_edit(query, f"Erro ao salvar evento na planilha: {e}")
        return

    # Resultado pode ser bool, id, dict... vamos tentar extrair um ID utilizável
    id_evento = ""
    if isinstance(resultado, str):
        id_evento = resultado
    elif isinstance(resultado, dict):
        id_evento = _norm_text(resultado.get("ID Evento") or resultado.get("id_evento") or "")
    if not id_evento:
        # fallback: gera um id estável para callbacks, mas o ideal é o Sheets retornar/armazenar
        id_evento = str(uuid.uuid4())

    # 2) Publica no grupo
    grupo_id = _norm_text(context.user_data.get("novo_evento_telegram_id_grupo", GRUPO_PRINCIPAL_ID))
    try:
        grupo_id_int = int(float(grupo_id))
    except Exception:
        grupo_id_int = int(GRUPO_PRINCIPAL_ID)

    nome = _escape_md(evento.get("Nome da loja", ""))
    numero = _escape_md(evento.get("Número da loja", ""))
    numero_fmt = f" {numero}" if numero and numero != "0" else ""
    data_txt = _escape_md(evento.get("Data do evento", ""))
    hora_txt = _escape_md(evento.get("Hora", ""))
    oriente = _escape_md(evento.get("Oriente", ""))
    potencia = _escape_md(evento.get("Potência", ""))
    grau = _escape_md(evento.get("Grau", ""))

    texto_grupo = (
        "*🐐 Novo Evento*\n\n"
        f"🏛 {nome}{numero_fmt}\n"
        f"📅 {data_txt}\n"
        f"🕕 {hora_txt}\n"
        f"📍 {oriente}\n"
        f"⚜️ {potencia}\n"
        f"🔺 Grau mínimo: {grau}\n"
    )

    try:
        await context.bot.send_message(
            chat_id=grupo_id_int,
            text=texto_grupo,
            parse_mode="Markdown",
            reply_markup=_teclado_pos_publicacao(id_evento),
        )
    except Exception as e:
        # Mesmo se falhar publicar no grupo, o evento já foi salvo
        await _safe_edit(query, f"Evento salvo, mas falhou ao publicar no grupo: {e}")
        _limpar_contexto_evento(context)
        return

    # 3) Confirma no privado
    msg = "✅ Evento cadastrado e publicado no grupo."
    if forcar:
        msg += " (publicado com duplicidade assumida)"
    await _safe_edit(query, msg)

    _limpar_contexto_evento(context)


async def refazer_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔄 Reiniciando cadastro...")

    # preserva IDs do grupo/secretário e limpa o resto
    tg_grupo = context.user_data.get("novo_evento_telegram_id_grupo", GRUPO_PRINCIPAL_ID)
    tg_sec = context.user_data.get("novo_evento_telegram_id_secretario", "")
    _limpar_contexto_evento(context)
    context.user_data["novo_evento_telegram_id_grupo"] = tg_grupo
    context.user_data["novo_evento_telegram_id_secretario"] = tg_sec

    await _safe_edit(
        query,
        "Vamos recomeçar o cadastro.\n\nQual a *Data do evento*? (Ex: 25/03/2026)",
        parse_mode="Markdown",
        reply_markup=_teclado_cancelar(),
    )
    return DATA


# =========================
# Navegação (Voltar/Cancelar)
# =========================
async def ev_voltar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⬅️ Voltando...")

    estado = _voltar_um_passo(context)
    # Após remover um campo, reapresenta a pergunta correspondente
    return await _ir_proximo_passo_por_callback(query, context)


async def ev_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer("❌ Cadastro cancelado")
        await _safe_edit(query, "Cadastro cancelado. Use /start para voltar ao menu principal.")
    else:
        if update.message:
            await update.message.reply_text("Cadastro cancelado. Use /start para voltar ao menu principal.")

    _limpar_contexto_evento(context)
    return ConversationHandler.END


async def cancelar_publicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("❌ Cancelando...")
    await _safe_edit(query, "Cadastro cancelado. Use /start para voltar ao menu principal.")
    _limpar_contexto_evento(context)
    return ConversationHandler.END


async def cancelar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Cadastro de evento cancelado. Use /start para voltar ao menu principal.")
    _limpar_contexto_evento(context)
    return ConversationHandler.END


# =========================
# ConversationHandler
# =========================
cadastro_evento_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(novo_evento_start, pattern=r"^cadastrar_evento$")],
    states={
        ESCOLHER_LOJA: [CallbackQueryHandler(escolher_loja_callback, pattern="^(usar_loja_|cadastrar_manual)$")],
        DATA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_data),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        HORARIO: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_horario),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        NOME_LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_nome_loja),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        NUMERO_LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_numero_loja),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        ORIENTE: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_oriente),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        GRAU: [
            CallbackQueryHandler(receber_grau_callback, pattern=r"^grau\|"),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        TIPO_SESSAO: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_tipo_sessao),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        RITO: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_rito),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        POTENCIA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_potencia),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        TRAJE: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_traje),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        AGAPE: [
            CallbackQueryHandler(receber_agape, pattern=r"^agape\|"),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        AGAPE_TIPO: [
            CallbackQueryHandler(receber_agape_tipo, pattern=r"^agape_tipo\|"),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        OBSERVACOES_TEM: [
            CallbackQueryHandler(receber_observacoes_tem, pattern=r"^obs\|"),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        OBSERVACOES_TEXTO: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_observacoes_texto),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        ENDERECO: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_endereco),
            CallbackQueryHandler(ev_voltar, pattern=r"^ev_voltar$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_publicacao, pattern=r"^confirmar_publicacao$"),
            CallbackQueryHandler(confirmar_publicacao_forcar, pattern=r"^confirmar_publicacao_forcar$"),
            CallbackQueryHandler(refazer_cadastro, pattern=r"^refazer_cadastro$"),
            CallbackQueryHandler(cancelar_publicacao, pattern=r"^cancelar_publicacao$"),
            CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_cadastro_evento),
        CallbackQueryHandler(ev_cancelar, pattern=r"^ev_cancelar$"),
    ],
    allow_reentry=True,
    name="cadastro_evento_handler",
    persistent=False,
)