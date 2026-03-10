# src/cadastro_evento.py
# ============================================
# BODE ANDARILHO - CADASTRO DE EVENTOS
# ============================================
# 
# Este módulo gerencia o cadastro de novos eventos por secretários e administradores.
# 
# Funcionalidades principais:
# - Cadastro completo com 16 etapas (data, horário, loja, grau, etc.)
# - Integração com pré-cadastro de lojas (atalho)
# - Verificação de duplicidade de eventos
# - Publicação automática no grupo
# - Navegação com botões Voltar/Cancelar
# - Cada etapa mostra APENAS a pergunta atual (sem acumular respostas)
# 
# ============================================

from __future__ import annotations

import os
import re
import uuid
import logging
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

from src.sheets_supabase import cadastrar_evento, listar_eventos, listar_lojas
from src.ajuda.dicas import enviar_dica_contextual
from src.permissoes import get_nivel
from src.bot import (
    navegar_para,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

# ============================================
# CONFIGURAÇÃO DE LOG
# ============================================

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID", "-1003721338228")
MAX_TEXTO = 250

# Estados da conversação
(
    ESCOLHER_LOJA,
    CONFIRMAR_LOJA,
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
) = range(18)

# Opções fixas
GRAUS_OPCOES = [
    ("Aprendiz", "Aprendiz"),
    ("Companheiro", "Companheiro"),
    ("Mestre", "Mestre"),
    ("Mestre Instalado", "Mestre Instalado"),
]

AGAPE_RESPOSTAS = [("Sim", "sim"), ("Não", "nao")]
AGAPE_TIPOS = [("Gratuito", "gratuito"), ("Pago (dividido)", "pago")]
OBS_RESPOSTAS = [("Sim", "sim"), ("Não", "nao")]


# ============================================
# FUNÇÕES AUXILIARES
# ============================================

def _norm_text(v: Any) -> str:
    """Normaliza texto, removendo NaN e espaços."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _truncate(s: str, n: int = MAX_TEXTO) -> str:
    """Limita o tamanho do texto."""
    s = _norm_text(s)
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _escape_md(s: str) -> str:
    """Escapa caracteres especiais do Markdown."""
    s = _norm_text(s)
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def _parse_data_ddmmyyyy(texto: str) -> Optional[datetime]:
    """Converte string DD/MM/AAAA para datetime."""
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y")
    except Exception:
        return None


def _parse_hora(texto: str) -> Optional[str]:
    """Converte HH:MM ou HH:MM:SS para HH:MM."""
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


def _tipo_agape_evento(texto_agape: str) -> str:
    """Detecta o tipo de ágape salvo no evento."""
    texto = _norm_text(texto_agape).lower()
    if "pago" in texto or "dividido" in texto:
        return "pago"
    if "gratuito" in texto:
        return "gratuito"
    if "com ágape" in texto or "com agape" in texto:
        return "com"
    if texto in ("sim", "s"):
        return "com"
    return "sem"


def _dia_semana_ingles(dt: datetime) -> str:
    """Retorna o dia da semana em inglês."""
    return dt.strftime("%A")


def _teclado_cancelar() -> InlineKeyboardMarkup:
    """Teclado com apenas botão Cancelar."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")]])


def _teclado_voltar_cancelar() -> InlineKeyboardMarkup:
    """Teclado com botões Voltar e Cancelar."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")],
        ]
    )


def _teclado_sim_nao(prefix: str) -> InlineKeyboardMarkup:
    """Teclado para perguntas Sim/Não."""
    opcoes = AGAPE_RESPOSTAS if prefix == "agape" else OBS_RESPOSTAS
    linhas = [[InlineKeyboardButton(lbl, callback_data=f"{prefix}|{val}")] for (lbl, val) in opcoes]
    linhas.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_graus() -> InlineKeyboardMarkup:
    """Teclado com opções de grau."""
    linhas = [[InlineKeyboardButton(lbl, callback_data=f"grau|{val}")] for (lbl, val) in GRAUS_OPCOES]
    linhas.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_agape_tipos() -> InlineKeyboardMarkup:
    """Teclado com tipos de ágape."""
    linhas = [[InlineKeyboardButton(lbl, callback_data=f"agape_tipo|{val}")] for (lbl, val) in AGAPE_TIPOS]
    linhas.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ev_voltar")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _event_key(data: str, hora: str, nome: str, numero: str) -> str:
    """Gera chave única para detecção de duplicidade."""
    return f"{_norm_text(data)}|{_norm_text(hora)}|{_norm_text(nome).lower()}|{_norm_text(numero)}"


def _status_ativo_ou_vazio(status: str) -> bool:
    """Verifica se o status é ativo ou vazio."""
    s = _norm_text(status).lower()
    return s == "" or s == "ativo"


def _encontrar_duplicado(evento: Dict[str, Any], eventos_existentes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Verifica se já existe um evento duplicado."""
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
    """Monta o dicionário do evento com os dados coletados."""
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
    """Limpa todos os dados de evento do context."""
    for k in list(context.user_data.keys()):
        if k.startswith("novo_evento_"):
            context.user_data.pop(k, None)
    context.user_data.pop("lojas_disponiveis", None)
    context.user_data.pop("loja_selecionada", None)


def _voltar_um_passo(context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Remove o último campo preenchido e retorna ao estado anterior.
    Respeita os ramos condicionais (ágape_tipo só se ágape==sim, etc.).
    """
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


def _montar_resumo_evento_md(evento: Dict[str, Any], duplicado: Optional[Dict[str, Any]] = None) -> str:
    """Monta o resumo do evento para confirmação."""
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
    """Teclado para tela de confirmação.

    Quando há duplicidade mostramos apenas a opção de "Publicar mesmo assim";
    o botão "Confirmar publicação" anterior fazia o fluxo repetir a mesma tela
    (o que confundia os usuários).
    """
    linhas = []
    if tem_duplicado:
        linhas.append([InlineKeyboardButton("⚠️ Publicar mesmo assim", callback_data="confirmar_publicacao_forcar")])
    else:
        linhas.append([InlineKeyboardButton("✅ Confirmar publicação", callback_data="confirmar_publicacao")])
    linhas.append([InlineKeyboardButton("🔄 Refazer", callback_data="refazer_cadastro")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_publicacao")])
    return InlineKeyboardMarkup(linhas)


def _teclado_pos_publicacao(id_evento: str, agape_evento: str) -> InlineKeyboardMarkup:
    """Teclado para mensagem publicada no grupo."""
    tipo_agape = _tipo_agape_evento(agape_evento)
    linhas = []

    if tipo_agape == "gratuito":
        linhas.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{id_evento}|gratuito")])
        linhas.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
    elif tipo_agape == "pago":
        linhas.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{id_evento}|pago")])
        linhas.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
    elif tipo_agape == "com":
        linhas.append([InlineKeyboardButton("🍽 Participar com ágape", callback_data=f"confirmar|{id_evento}|com")])
        linhas.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
    else:
        linhas.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento}|sem")])

    linhas.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento}")])
    return InlineKeyboardMarkup(linhas)


# ============================================
# INÍCIO DO CADASTRO (COM INTEGRAÇÃO DE LOJAS)
# ============================================

async def novo_evento_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o cadastro de um novo evento."""
    query = update.callback_query
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Você não tem permissão para cadastrar eventos.",
            limpar_conteudo=True
        )
        return ConversationHandler.END

    # Armazena o ID do usuário que está cadastrando
    context.user_data["novo_evento_telegram_id_secretario"] = str(user_id)

    # Se veio do grupo, bloqueia e orienta
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        context.user_data["novo_evento_telegram_id_grupo"] = str(update.effective_chat.id)
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🔔 O cadastro de eventos deve ser feito no meu chat privado.\n\n"
            "Acesse meu privado e utilize o menu 'Área do Secretário' para cadastrar.",
            limpar_conteudo=True
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
        for i, loja in enumerate(lojas[:5]):
            nome = loja.get("Nome da Loja", "")
            numero = loja.get("Número", "")
            nome_fmt = f"{nome} {numero}" if numero else nome
            botoes_lojas.append([
                InlineKeyboardButton(
                    f"🏛 {nome_fmt}",
                    callback_data=f"usar_loja_{i}"
                )
            ])
        
        botoes_lojas.append([InlineKeyboardButton("📝 Cadastrar manualmente", callback_data="cadastrar_manual")])
        botoes_lojas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
        
        context.user_data["lojas_disponiveis"] = lojas
        
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "🏛️ *Cadastro de Evento*\n\nVocê tem lojas cadastradas. Deseja usar os dados de alguma como atalho?",
            InlineKeyboardMarkup(botoes_lojas),
            limpar_conteudo=True
        )
        return ESCOLHER_LOJA
    else:
        # Segue fluxo normal (sempre tem opção manual)
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "📅 *Data do evento* (Ex: 25/03/2026)",
            _teclado_cancelar(),
            limpar_conteudo=True
        )
        await enviar_dica_contextual(update, context, "cadastro_evento_data")
        return DATA


async def escolher_loja_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa a escolha da loja pelo secretário."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    if data == "cadastrar_manual":
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "📅 *Data do evento* (Ex: 25/03/2026)",
            _teclado_cancelar(),
            limpar_conteudo=True
        )
        await enviar_dica_contextual(update, context, "cadastro_evento_data")
        return DATA
    
    if data.startswith("usar_loja_"):
        try:
            index = int(data.split("_")[2])
            lojas = context.user_data.get("lojas_disponiveis", [])
            
            if 0 <= index < len(lojas):
                loja = lojas[index]
                # Guarda a loja selecionada
                context.user_data["loja_selecionada"] = loja
                
                # Mostra os dados da loja e pergunta confirmação
                dados_loja = (
                    f"🏛 *{loja.get('Nome da Loja')}* {loja.get('Número', '')}\n"
                    f"📍 Oriente: {loja.get('Oriente da Loja', loja.get('Oriente', ''))}\n"
                    f"📜 Rito: {loja.get('Rito')}\n"
                    f"⚜️ Potência: {loja.get('Potência')}\n"
                    f"📍 Endereço: {loja.get('Endereço')}\n\n"
                    f"Deseja usar esta loja?"
                )
                
                teclado = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Sim, usar esta loja", callback_data="confirmar_loja_sim")],
                    [InlineKeyboardButton("❌ Não, escolher outra", callback_data="escolher_outra_loja")],
                    [InlineKeyboardButton("📝 Cadastrar manualmente", callback_data="cadastrar_manual")],
                ])
                
                await navegar_para(
                    update, context,
                    "Cadastro de Evento > Confirmar Loja",
                    dados_loja,
                    teclado,
                    limpar_conteudo=True
                )
                return CONFIRMAR_LOJA
            else:
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    "❌ Loja não encontrada. Tente novamente.",
                    limpar_conteudo=True
                )
                return ESCOLHER_LOJA
        except (ValueError, IndexError) as e:
            logger.error(f"Erro ao processar seleção de loja: {e}")
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "❌ Erro ao processar seleção. Tente novamente.",
                limpar_conteudo=True
            )
            return ESCOLHER_LOJA
    
    # Se chegou aqui, comando inválido
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO,
        "❌ Comando inválido. Tente novamente.",
        limpar_conteudo=True
    )
    return ESCOLHER_LOJA


# ============================================
# CONFIRMAÇÃO DE LOJA (CORRIGIDO COM LOGGER)
# ============================================

async def confirmar_loja_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma o uso da loja selecionada."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    # Log para debug (agora com logger definido)
    logger.info(f"confirmar_loja_callback chamado com data: {data}")

    if data == "confirmar_loja_sim":
        loja = context.user_data.get("loja_selecionada")
        if loja:
            # Pré-preenche os dados da loja
            context.user_data["novo_evento_nome_loja"] = loja.get("Nome da Loja", "")
            context.user_data["novo_evento_numero_loja"] = str(loja.get("Número", "0"))
            context.user_data["novo_evento_oriente"] = loja.get("Oriente da Loja", loja.get("Oriente", ""))
            context.user_data["novo_evento_rito"] = loja.get("Rito", "")
            context.user_data["novo_evento_potencia"] = loja.get("Potência", "")
            context.user_data["novo_evento_endereco"] = loja.get("Endereço", "")
            
            await navegar_para(
                update, context,
                "Cadastro de Evento",
                "📅 *Data do evento* (Ex: 25/03/2026)",
                _teclado_voltar_cancelar(),
                limpar_conteudo=True
            )
            await enviar_dica_contextual(update, context, "cadastro_evento_data")
            return DATA
        else:
            await navegar_para(
                update, context,
                "Cadastro de Evento",
                "Erro ao carregar loja. Tente novamente.",
                _teclado_cancelar(),
                limpar_conteudo=True
            )
            return ESCOLHER_LOJA
    
    elif data == "escolher_outra_loja":
        # Volta para a escolha de lojas
        lojas = context.user_data.get("lojas_disponiveis", [])
        botoes_lojas = []
        for i, loja in enumerate(lojas[:5]):
            nome = loja.get("Nome da Loja", "")
            numero = loja.get("Número", "")
            nome_fmt = f"{nome} {numero}" if numero else nome
            botoes_lojas.append([
                InlineKeyboardButton(
                    f"🏛 {nome_fmt}",
                    callback_data=f"usar_loja_{i}"
                )
            ])
        
        botoes_lojas.append([InlineKeyboardButton("📝 Cadastrar manualmente", callback_data="cadastrar_manual")])
        botoes_lojas.append([InlineKeyboardButton("❌ Cancelar", callback_data="ev_cancelar")])
        
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "🏛️ *Cadastro de Evento*\n\nEscolha uma loja:",
            InlineKeyboardMarkup(botoes_lojas),
            limpar_conteudo=True
        )
        return ESCOLHER_LOJA
    
    elif data == "cadastrar_manual":
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "📅 *Data do evento* (Ex: 25/03/2026)",
            _teclado_cancelar(),
            limpar_conteudo=True
        )
        await enviar_dica_contextual(update, context, "cadastro_evento_data")
        return DATA
    
    # Se chegou aqui, comando não reconhecido
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO,
        "❌ Opção inválida. Tente novamente.",
        limpar_conteudo=True
    )
    return CONFIRMAR_LOJA


# ============================================
# RECEBEDORES DE DADOS (TEXTO) - COM LIMPEZA
# ============================================

async def receber_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe e valida a data do evento."""
    try:
        await update.message.delete()
    except:
        pass
    data_text = _norm_text(update.message.text)
    dt = _parse_data_ddmmyyyy(data_text)
    if not dt:
        # mostra o erro na própria mensagem de resultado (mantém teclado)
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Data inválida. Use o formato *dd/mm/aaaa* (Ex: 25/03/2026).",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True,
        )
        return DATA

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if dt < hoje:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "A data não pode ser no passado. Tente novamente:",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True,
        )
        return DATA

    context.user_data["novo_evento_data"] = dt.strftime("%d/%m/%Y")
    
    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "🕕 *Horário* (Ex: 19:30)",
        _teclado_voltar_cancelar(),
        limpar_conteudo=True
    )
    return HORARIO


async def receber_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe e valida o horário."""
    try:
        await update.message.delete()
    except:
        pass
    hora = _parse_hora(update.message.text)
    if not hora:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Horário inválido. Use *HH:MM* (Ex: 19:30).",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True,
        )
        return HORARIO

    context.user_data["novo_evento_horario"] = hora
    
    # Se já tem nome da loja pré-carregada (veio de loja cadastrada), pula para grau
    if "novo_evento_nome_loja" in context.user_data:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "🔺 *Grau mínimo*",
            _teclado_graus(),
            limpar_conteudo=True
        )
        return GRAU
    else:
        # Fluxo manual: pergunta o nome da loja
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "🏛 *Nome da loja*",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        return NOME_LOJA


async def receber_nome_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o nome da loja - chamado tanto do fluxo manual quanto da confirmação de loja."""
    try:
        await update.message.delete()
    except:
        pass
    nome = _truncate(update.message.text)
    if not nome:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Informe um nome válido para a loja.",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True,
        )
        return NOME_LOJA

    context.user_data["novo_evento_nome_loja"] = nome
    
    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "🔢 *Número da loja* (se não houver, digite 0)",
        _teclado_voltar_cancelar(),
        limpar_conteudo=True
    )
    return NUMERO_LOJA


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o número da loja - etapa intermediária entre NOME_LOJA e ORIENTE."""
    try:
        await update.message.delete()
    except:
        pass
    numero = _norm_text(update.message.text)
    numero = _truncate(numero, 30)
    if not numero:
        numero = "0"

    context.user_data["novo_evento_numero_loja"] = numero
    
    # Se já tem oriente pré-carregada (veio de loja cadastrada), pula para grau
    if "novo_evento_oriente" in context.user_data:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "🔺 *Grau mínimo* (Aprendiz, Companheiro, Mestre)",
            _teclado_graus(),
            limpar_conteudo=True
        )
        return GRAU
    else:
        # Continua com pergunta do oriente
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "📍 *Oriente*",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        return ORIENTE


async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o oriente."""
    try:
        await update.message.delete()
    except:
        pass
    oriente = _truncate(update.message.text)
    if not oriente:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Informe um oriente válido.",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True,
        )
        return ORIENTE

    context.user_data["novo_evento_oriente"] = oriente
    
    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "🔺 *Grau mínimo*",
        _teclado_graus(),
        limpar_conteudo=True
    )
    return GRAU


# ============================================
# RECEBEDOR DE GRAU (BOTÕES)
# ============================================

async def receber_grau_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o grau selecionado via botão."""
    query = update.callback_query
    await query.answer()

    _, grau = query.data.split("|", 1)
    grau = _norm_text(grau)

    permitidos = {v for _, v in GRAUS_OPCOES}
    if grau not in permitidos:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Grau inválido. Selecione uma opção:",
            _teclado_graus(),
            limpar_conteudo=True
        )
        return GRAU

    # Salva o grau escolhido
    context.user_data["novo_evento_grau"] = grau

    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "🕯 *Tipo de sessão* (texto livre)",
        _teclado_voltar_cancelar(),
        limpar_conteudo=True
    )
    return TIPO_SESSAO


# ============================================
# RECEBEDORES DAS PRÓXIMAS ETAPAS
# ============================================

async def receber_tipo_sessao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o tipo de sessão."""
    try:
        await update.message.delete()
    except:
        pass
    val = _truncate(update.message.text)
    context.user_data["novo_evento_tipo_sessao"] = val
    
    # Se já tem rito (veio de cadastro com loja), pula
    if "novo_evento_rito" in context.user_data:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "👔 *Traje obrigatório* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        return TRAJE
    else:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "📜 *Rito* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        return RITO


async def receber_rito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o rito."""
    try:
        await update.message.delete()
    except:
        pass
    val = _truncate(update.message.text)
    context.user_data["novo_evento_rito"] = val
    
    # Se já tem potência (veio de cadastro com loja), pula
    if "novo_evento_potencia" in context.user_data:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "👔 *Traje obrigatório* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        return TRAJE
    else:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "⚜️ *Potência* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a potência."""
    try:
        await update.message.delete()
    except:
        pass
    val = _truncate(update.message.text)
    context.user_data["novo_evento_potencia"] = val
    
    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "👔 *Traje obrigatório* (texto livre)",
        _teclado_voltar_cancelar(),
        limpar_conteudo=True
    )
    return TRAJE


async def receber_traje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o traje obrigatório."""
    val = _truncate(update.message.text)
    context.user_data["novo_evento_traje"] = val
    
    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "🍽 *Haverá Ágape?*",
        _teclado_sim_nao("agape"),
        limpar_conteudo=True
    )
    return AGAPE


# ============================================
# FLUXOS POR BOTÕES (ÁGAPE, OBSERVAÇÕES)
# ============================================

async def receber_agape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa resposta sobre ágape."""
    query = update.callback_query
    await query.answer()
    _, val = query.data.split("|", 1)
    val = _norm_text(val)

    if val not in ("sim", "nao"):
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Selecione uma opção:",
            _teclado_sim_nao("agape"),
            limpar_conteudo=True
        )
        return AGAPE

    context.user_data["novo_evento_agape"] = val
    context.user_data.pop("novo_evento_agape_tipo", None)

    if val == "sim":
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "💰 *Tipo de Ágape?*",
            _teclado_agape_tipos(),
            limpar_conteudo=True
        )
        return AGAPE_TIPO

    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "📝 *Deseja adicionar observações?*",
        _teclado_sim_nao("obs"),
        limpar_conteudo=True
    )
    return OBSERVACOES_TEM


async def receber_agape_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa o tipo de ágape."""
    query = update.callback_query
    await query.answer()
    _, val = query.data.split("|", 1)
    val = _norm_text(val)

    if val not in ("gratuito", "pago"):
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Selecione uma opção:",
            _teclado_agape_tipos(),
            limpar_conteudo=True
        )
        return AGAPE_TIPO

    context.user_data["novo_evento_agape_tipo"] = val
    
    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "📝 *Deseja adicionar observações?*",
        _teclado_sim_nao("obs"),
        limpar_conteudo=True
    )
    return OBSERVACOES_TEM


async def receber_observacoes_tem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa se haverá observações."""
    query = update.callback_query
    await query.answer()
    _, val = query.data.split("|", 1)
    val = _norm_text(val)

    if val not in ("sim", "nao"):
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Selecione uma opção:",
            _teclado_sim_nao("obs"),
            limpar_conteudo=True
        )
        return OBSERVACOES_TEM

    context.user_data["novo_evento_observacoes_tem"] = val
    context.user_data.pop("novo_evento_observacoes_texto", None)

    if val == "sim":
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "✏️ *Digite as observações* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        return OBSERVACOES_TEXTO

    # Se já tem endereço (veio de cadastro com loja), pula para confirmação
    if "novo_evento_endereco" in context.user_data:
        evento = _montar_evento_dict(context)
        eventos_existentes = listar_eventos() or []
        dup = _encontrar_duplicado(evento, eventos_existentes)
        
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            _montar_resumo_evento_md(evento, duplicado=dup),
            _teclado_confirmacao(tem_duplicado=dup is not None),
            limpar_conteudo=True
        )
        return CONFIRMAR
    else:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "📍 *Endereço da sessão*",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        await enviar_dica_contextual(update, context, "cadastro_evento_endereco")
        return ENDERECO


async def receber_observacoes_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o texto das observações."""
    val = _truncate(update.message.text, 500)
    context.user_data["novo_evento_observacoes_texto"] = val
    
    # Se já tem endereço (veio de cadastro com loja), pula para confirmação
    if "novo_evento_endereco" in context.user_data:
        evento = _montar_evento_dict(context)
        eventos_existentes = listar_eventos() or []
        dup = _encontrar_duplicado(evento, eventos_existentes)
        
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            _montar_resumo_evento_md(evento, duplicado=dup),
            _teclado_confirmacao(tem_duplicado=dup is not None),
            limpar_conteudo=True
        )
        return CONFIRMAR
    else:
        await navegar_para(
            update, context,
            "Cadastro de Evento",
            "📍 *Endereço da sessão*",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        await enviar_dica_contextual(update, context, "cadastro_evento_endereco")
        return ENDERECO


async def receber_endereco(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o endereço e exibe tela de confirmação."""
    try:
        await update.message.delete()
    except:
        pass
    val = _truncate(update.message.text, 400)
    if len(val) < 3:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Endereço muito curto. Digite novamente:",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True,
        )
        return ENDERECO
    context.user_data["novo_evento_endereco"] = val

    evento = _montar_evento_dict(context)
    eventos_existentes = listar_eventos() or []
    dup = _encontrar_duplicado(evento, eventos_existentes)

    await navegar_para(
        update, context,
        "Cadastro de Evento",
        _montar_resumo_evento_md(evento, duplicado=dup),
        _teclado_confirmacao(tem_duplicado=dup is not None),
        limpar_conteudo=True
    )
    return CONFIRMAR


# ============================================
# CONFIRMAÇÃO / PUBLICAÇÃO
# ============================================

async def confirmar_publicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e publica o evento (verificando duplicidade)."""
    query = update.callback_query
    await query.answer()

    evento = _montar_evento_dict(context)
    eventos_existentes = listar_eventos() or []
    dup = _encontrar_duplicado(evento, eventos_existentes)
    
    if dup:
        # ao invés de reapresentar a tela idêntica, mostra um alerta explicando a ação
        await query.answer("Existe duplicidade. Use 'Publicar mesmo assim' se quiser.", show_alert=True)
        return CONFIRMAR

    await _publicar_e_finalizar(update, context, evento)
    return ConversationHandler.END


async def confirmar_publicacao_forcar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Publica o evento mesmo com duplicidade."""
    query = update.callback_query
    await query.answer()

    evento = _montar_evento_dict(context)
    await _publicar_e_finalizar(update, context, evento, forcar=True)
    return ConversationHandler.END


async def _publicar_e_finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE, evento: Dict[str, Any], forcar: bool = False):
    """Salva o evento na planilha e publica no grupo."""
    user_id = update.effective_user.id
    
    # 1) Salva no Sheets
    try:
        resultado = cadastrar_evento(evento)
    except Exception as e:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            f"Erro ao salvar evento na planilha: {e}",
            limpar_conteudo=True
        )
        return

    # Extrai ID do evento
    id_evento = ""
    if isinstance(resultado, str):
        id_evento = resultado
    elif isinstance(resultado, dict):
        id_evento = _norm_text(resultado.get("ID Evento") or resultado.get("id_evento") or "")
    if not id_evento:
        id_evento = str(uuid.uuid4())

    # 2) Publica no grupo
    grupo_id = _norm_text(context.user_data.get("novo_evento_telegram_id_grupo", GRUPO_PRINCIPAL_ID))
    try:
        grupo_id_int = int(float(grupo_id))
    except Exception:
        grupo_id_int = int(GRUPO_PRINCIPAL_ID)

    # Escapa caracteres especiais para Markdown
    nome = _escape_md(evento.get("Nome da loja", ""))
    numero = _escape_md(evento.get("Número da loja", ""))
    numero_fmt = f" {numero}" if numero and numero != "0" else ""
    data_txt = _escape_md(evento.get("Data do evento", ""))
    hora_txt = _escape_md(evento.get("Hora", ""))
    oriente = _escape_md(evento.get("Oriente", ""))
    potencia = _escape_md(evento.get("Potência", ""))
    grau = _escape_md(evento.get("Grau", ""))
    tipo = _escape_md(evento.get("Tipo de sessão", ""))
    rito = _escape_md(evento.get("Rito", ""))
    traje = _escape_md(evento.get("Traje obrigatório", ""))
    agape = _escape_md(evento.get("Ágape", ""))
    endereco = _escape_md(evento.get("Endereço da sessão", ""))
    observacao = _escape_md(evento.get("Observações", "")) or "-"

    texto_grupo = (
        "*NOVA SESSÃO!*\n\n"
        f"*{data_txt}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*{grau}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_{nome}{numero_fmt}_\n"
        f"_{oriente} - {potencia}_\n\n"
        f"Horário: {hora_txt}\n"
        f"Tipo: {tipo}\n"
        f"Rito: {rito}\n"
        f"Traje: {traje}\n"
        f"Ágape: {agape}\n"
        f"Endereço: {endereco}\n"
        f"Observação: {observacao}"
    )

    try:
        await context.bot.send_message(
            chat_id=grupo_id_int,
            text=texto_grupo,
            parse_mode="Markdown",
            reply_markup=_teclado_pos_publicacao(id_evento, evento.get("Ágape", "")),
        )
    except Exception as e:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            f"Evento salvo, mas falhou ao publicar no grupo: {e}",
            limpar_conteudo=True
        )
        _limpar_contexto_evento(context)
        return

    # 3) Confirma no privado
    msg = "✅ Evento cadastrado e publicado no grupo."
    if forcar:
        msg += " (publicado com duplicidade assumida)"
    
    await navegar_para(
        update, context,
        "Cadastro Concluído",
        msg,
        InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")
        ]]),
        limpar_conteudo=True
    )

    _limpar_contexto_evento(context)


async def refazer_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reinicia o cadastro do zero."""
    query = update.callback_query
    await query.answer()

    tg_grupo = context.user_data.get("novo_evento_telegram_id_grupo", GRUPO_PRINCIPAL_ID)
    tg_sec = context.user_data.get("novo_evento_telegram_id_secretario", "")
    _limpar_contexto_evento(context)
    context.user_data["novo_evento_telegram_id_grupo"] = tg_grupo
    context.user_data["novo_evento_telegram_id_secretario"] = tg_sec

    await navegar_para(
        update, context,
        "Cadastro de Evento",
        "📅 *Data do evento* (Ex: 25/03/2026)",
        _teclado_cancelar(),
        limpar_conteudo=True
    )
    await enviar_dica_contextual(update, context, "cadastro_evento_data")
    return DATA


# ============================================
# NAVEGAÇÃO (VOLTAR/CANCELAR)
# ============================================

async def ev_voltar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Volta para o passo anterior."""
    query = update.callback_query
    await query.answer()

    estado = _voltar_um_passo(context)
    
    # Reapresenta a pergunta do estado correspondente
    user_id = update.effective_user.id
    
    if estado == DATA:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "📅 *Data do evento* (Ex: 25/03/2026)",
            _teclado_cancelar(),
            limpar_conteudo=True
        )
        await enviar_dica_contextual(update, context, "cadastro_evento_data")
    elif estado == HORARIO:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🕕 *Horário* (Ex: 19:30)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == NOME_LOJA:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🏛 *Nome da loja*",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == NUMERO_LOJA:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🔢 *Número da loja* (se não houver, digite 0)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == ORIENTE:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "📍 *Oriente*",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == GRAU:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🔺 *Grau mínimo*",
            _teclado_graus(),
            limpar_conteudo=True
        )
    elif estado == TIPO_SESSAO:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🕯 *Tipo de sessão* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == RITO:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "📜 *Rito* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == POTENCIA:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚜️ *Potência* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == TRAJE:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "👔 *Traje obrigatório* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == AGAPE:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "🍽 *Haverá Ágape?*",
            _teclado_sim_nao("agape"),
            limpar_conteudo=True
        )
    elif estado == AGAPE_TIPO:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "💰 *Tipo de Ágape?*",
            _teclado_agape_tipos(),
            limpar_conteudo=True
        )
    elif estado == OBSERVACOES_TEM:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "📝 *Deseja adicionar observações?*",
            _teclado_sim_nao("obs"),
            limpar_conteudo=True
        )
    elif estado == OBSERVACOES_TEXTO:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "✏️ *Digite as observações* (texto livre)",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
    elif estado == ENDERECO:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "📍 *Endereço da sessão*",
            _teclado_voltar_cancelar(),
            limpar_conteudo=True
        )
        await enviar_dica_contextual(update, context, "cadastro_evento_endereco")
    
    return estado


async def ev_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o cadastro."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        await query.answer()
        await navegar_para(
            update, context,
            "Cadastro Cancelado",
            "Cadastro cancelado. Use o menu acima para voltar.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")
            ]]),
            limpar_conteudo=True
        )
    else:
        if update.message:
            await update.message.reply_text("Cadastro cancelado. Use /start para voltar ao menu principal.")

    _limpar_contexto_evento(context)
    return ConversationHandler.END


async def cancelar_publicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela a publicação."""
    query = update.callback_query
    await query.answer()
    await ev_cancelar(update, context)
    return ConversationHandler.END


async def cancelar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela via comando /cancelar."""
    if update.message:
        await update.message.reply_text("Cadastro de evento cancelado. Use /start para voltar ao menu principal.")
    _limpar_contexto_evento(context)
    return ConversationHandler.END


# ============================================
# CONVERSATION HANDLER
# ============================================

cadastro_evento_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(novo_evento_start, pattern=r"^cadastrar_evento$")],
    states={
        ESCOLHER_LOJA: [CallbackQueryHandler(escolher_loja_callback, pattern="^(usar_loja_\\d+|cadastrar_manual)$")],
        CONFIRMAR_LOJA: [
            CallbackQueryHandler(confirmar_loja_callback, pattern="^(confirmar_loja_sim|escolher_outra_loja|cadastrar_manual)$")
        ],
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
