# src/eventos.py
# ============================================
# BODE ANDARILHO - GERENCIAMENTO DE EVENTOS
# ============================================
# 
# Este módulo gerencia todas as funcionalidades relacionadas a eventos:
# - Visualização de eventos com filtros (data, grau)
# - Calendário visual
# - Confirmação e cancelamento de presença
# - Lista de confirmados
# - Histórico de participação do usuário
# 
# ============================================

from __future__ import annotations

import logging
import urllib.parse
import calendar
import functools
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional, Tuple, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, CommandHandler

from src.sheets import (
    listar_eventos,
    buscar_membro,
    registrar_confirmacao,
    cancelar_confirmacao,
    buscar_confirmacao,
    listar_confirmacoes_por_evento,
    get_notificacao_status,
)
from src.ajuda.dicas import enviar_dica_contextual

from src.bot import (
    navegar_para,
    voltar_ao_menu_principal,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

MAX_EVENTOS_LISTA = 40
MESES_PROXIMOS_QTD = 6

MENSAGEM_CONFIRMACAO_AGAPE = (
    "Sua confirmação é muito importante! Ela nos ajuda a organizar tudo com carinho, "
    "evitando desperdícios e custos desnecessários.\n\n"
    "Fraterno abraço!"
)

# Tokens de filtro
TOKEN_SEMANA_ATUAL = "semana_atual"
TOKEN_PROXIMA_SEMANA = "proxima_semana"
TOKEN_MES_ATUAL = "mes_atual"
TOKEN_PROXIMOS_MESES = "proximos_meses"
TOKEN_POR_GRAU_MENU = "por_grau"

# Graus
GRAU_APRENDIZ = "Aprendiz"
GRAU_COMPANHEIRO = "Companheiro"
GRAU_MESTRE = "Mestre"

# Dias da semana (tradução)
DIAS_SEMANA = {
    "Monday": "Segunda-feira",
    "Tuesday": "Terça-feira",
    "Wednesday": "Quarta-feira",
    "Thursday": "Quinta-feira",
    "Friday": "Sexta-feira",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}

# ============================================
# FUNÇÕES AUXILIARES (NÃO VISUAIS)
# ============================================

def traduzir_dia(dia_ingles: str) -> str:
    return DIAS_SEMANA.get(dia_ingles, dia_ingles)


def traduzir_dia_abreviado(dia_ingles: str) -> str:
    dias_abreviados = {
        "Monday": "Segunda",
        "Tuesday": "Terça",
        "Wednesday": "Quarta",
        "Thursday": "Quinta",
        "Friday": "Sexta",
        "Saturday": "Sábado",
        "Sunday": "Domingo",
    }
    return dias_abreviados.get(dia_ingles, dia_ingles)


def extrair_tipo_agape(texto_agape: str) -> str:
    texto = (texto_agape or "").lower()
    if "pago" in texto or "dividido" in texto:
        return "pago"
    if "gratuito" in texto:
        return "gratuito"
    if "com ágape" in texto or "com agape" in texto:
        return "com"
    if texto.strip() in ("sim", "s"):
        return "com"
    return "sem"


def _teclado_confirmacao_evento(id_evento: str, agape_evento: str) -> List[List[InlineKeyboardButton]]:
    """Monta botões de confirmação conforme tipo de ágape da sessão."""
    id_cod = _encode_cb(id_evento)
    tipo_agape = extrair_tipo_agape(agape_evento)

    if tipo_agape == "gratuito":
        return [
            [InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{id_cod}|gratuito")],
            [InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_cod}|sem")],
        ]

    if tipo_agape == "pago":
        return [
            [InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{id_cod}|pago")],
            [InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_cod}|sem")],
        ]

    if tipo_agape == "com":
        return [
            [InlineKeyboardButton("🍽 Participar com ágape", callback_data=f"confirmar|{id_cod}|com")],
            [InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_cod}|sem")],
        ]

    return [[InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_cod}|sem")]]


def _texto_participacao_agape(tipo_agape: str) -> str:
    """Retorna texto humano para a escolha de participação no ágape."""
    if tipo_agape == "gratuito":
        return "Participação com ágape (gratuito) foi selecionada."
    if tipo_agape == "pago":
        return "Participação com ágape (pago) foi selecionada."
    if tipo_agape == "com":
        return "Participação com ágape foi selecionada."
    return "Participação sem ágape foi selecionada."


def normalizar_grau_nome(valor: str) -> str:
    v = (valor or "").strip().lower()

    if v in ("todos", "todo", "t", "am", "apr", "aprendiz"):
        return GRAU_APRENDIZ
    if v in ("comp", "companheiro", "c"):
        return GRAU_COMPANHEIRO
    if v in ("mest", "mestre", "m"):
        return GRAU_MESTRE
    if v in ("mi", "mestre instalado", "instalado", "mestreinstalado"):
        return "Mestre Instalado"

    return (valor or "").strip()


@functools.lru_cache(maxsize=1024)
def parse_data_evento(valor: Any) -> Optional[datetime]:
    if valor is None:
        return None

    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)

    texto = str(valor).strip()
    if not texto:
        return None

    formatos = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
    ]
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def _parse_hora(texto: Any) -> Tuple[int, int]:
    if texto is None:
        return (99, 99)
    try:
        s = str(texto).strip()
        if not s:
            return (99, 99)
        partes = s.split(":")
        hh = int(partes[0])
        mm = int(partes[1]) if len(partes) > 1 else 0
        return (hh, mm)
    except Exception:
        return (99, 99)


def _encode_cb(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _decode_cb(value: str) -> str:
    return urllib.parse.unquote(value)


def normalizar_id_evento(ev: dict) -> str:
    id_planilha = str(ev.get("ID Evento", "")).strip()
    if id_planilha and id_planilha.lower() != "nan":
        return id_planilha
    return f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"


def _tid_to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        s = str(value).strip()
        if not s or s.lower() == "nan":
            return None
        return int(float(s))
    except Exception:
        return None


def _eh_vm(dados: dict) -> bool:
    for k in ("Venerável Mestre", "Veneravel Mestre", "veneravel_mestre", "vm"):
        if k in dados:
            raw = str(dados.get(k) or "").strip().lower()
            return raw in ("sim", "s", "yes", "y", "1", "true")
    return False


def montar_linha_confirmado(dados_membro_ou_snapshot: dict) -> str:
    nome = (dados_membro_ou_snapshot.get("Nome") or dados_membro_ou_snapshot.get("nome") or "").strip()
    if _eh_vm(dados_membro_ou_snapshot) and nome:
        nome = f"VM {nome}"

    grau_raw = (dados_membro_ou_snapshot.get("Grau") or dados_membro_ou_snapshot.get("grau") or "").strip()
    grau = normalizar_grau_nome(grau_raw)

    loja = (dados_membro_ou_snapshot.get("Loja") or dados_membro_ou_snapshot.get("loja") or "").strip()
    numero = (dados_membro_ou_snapshot.get("Número da loja") or dados_membro_ou_snapshot.get("numero_loja") or "")
    numero = str(numero).strip()

    oriente = (dados_membro_ou_snapshot.get("Oriente") or dados_membro_ou_snapshot.get("oriente") or "").strip()
    potencia = (dados_membro_ou_snapshot.get("Potência") or dados_membro_ou_snapshot.get("potencia") or "").strip()

    loja_composta = f"{loja} {numero}".strip()
    return f"{nome} - {grau} - {loja_composta} - {oriente} - {potencia}"


def _data_range_semana(ref: date) -> Tuple[date, date]:
    start = ref - timedelta(days=ref.weekday())
    end = start + timedelta(days=6)
    return start, end


def _ultimo_dia_mes(ano: int, mes: int) -> date:
    if mes == 12:
        return date(ano, 12, 31)
    primeiro_prox = date(ano, mes + 1, 1)
    return primeiro_prox - timedelta(days=1)


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


@dataclass(frozen=True)
class EventoOrdenavel:
    evento: dict
    data_dt: Optional[datetime]
    hora_tuple: Tuple[int, int]

    @property
    def sort_key(self):
        dt = self.data_dt or datetime(2100, 1, 1)
        hh, mm = self.hora_tuple
        return (dt.date(), hh, mm, normalizar_id_evento(self.evento))


def _eventos_ordenados(eventos: List[dict]) -> List[dict]:
    tmp = []
    for ev in eventos:
        data_dt = parse_data_evento(ev.get("Data do evento", ""))
        hora_tuple = _parse_hora(ev.get("Hora", ""))
        tmp.append(EventoOrdenavel(ev, data_dt, hora_tuple))
    tmp.sort(key=lambda x: x.sort_key)
    return [x.evento for x in tmp]


def _filtrar_por_periodo(eventos: List[dict], token: str) -> Tuple[str, List[dict]]:
    hoje = date.today()

    if token == TOKEN_SEMANA_ATUAL:
        ini, fim = _data_range_semana(hoje)
        titulo = "Sessões — Esta semana"
    elif token == TOKEN_PROXIMA_SEMANA:
        ini0, fim0 = _data_range_semana(hoje)
        ini = ini0 + timedelta(days=7)
        fim = fim0 + timedelta(days=7)
        titulo = "Sessões — Próxima semana"
    elif token == TOKEN_MES_ATUAL:
        ini = date(hoje.year, hoje.month, 1)
        fim = _ultimo_dia_mes(hoje.year, hoje.month)
        titulo = "Sessões — Este mês"
    elif token == TOKEN_PROXIMOS_MESES:
        ini = hoje
        ini_mes_atual = date(hoje.year, hoje.month, 1)
        limite_inicio = _add_months(ini_mes_atual, MESES_PROXIMOS_QTD)
        fim = _ultimo_dia_mes(limite_inicio.year, limite_inicio.month)
        titulo = "Sessões — Próximos meses"
    else:
        return "Sessões", []

    filtrados = []
    for ev in eventos:
        data_dt = parse_data_evento(ev.get("Data do evento", ""))
        if not data_dt:
            continue
        d = data_dt.date()
        if ini <= d <= fim:
            filtrados.append(ev)

    return titulo, _eventos_ordenados(filtrados)


def _filtrar_por_grau(eventos: List[dict], grau_nome: str) -> Tuple[str, List[dict]]:
    alvo = normalizar_grau_nome(grau_nome)
    titulo = f"Sessões — Grau — {alvo}"

    filtrados = []
    for ev in eventos:
        g = normalizar_grau_nome(str(ev.get("Grau") or "").strip())
        if g == alvo:
            filtrados.append(ev)

    return titulo, _eventos_ordenados(filtrados)


def _formatar_data_curta(ev: dict) -> str:
    dt = parse_data_evento(ev.get("Data do evento", ""))
    if not dt:
        return str(ev.get("Data do evento", "") or "").strip() or "Sem data"
    dia_semana = traduzir_dia_abreviado(dt.strftime("%A"))
    return f"{dt.strftime('%d/%m')} ({dia_semana})"


def _linha_botao_evento(ev: dict) -> str:
    nome = str(ev.get("Nome da loja", "") or "").strip() or "Evento"
    numero = str(ev.get("Número da loja", "") or "").strip()
    hora = str(ev.get("Hora", "") or "").strip()

    numero_fmt = f" {numero}" if numero else ""
    hora_fmt = hora if hora else "—"
    data_curta = _formatar_data_curta(ev)

    return f"📅 {data_curta} • 🕕 {hora_fmt} • 🏛 {nome}{numero_fmt}"


# ============================================
# FUNÇÃO PARA NOTIFICAR SECRETÁRIO
# ============================================

async def notificar_secretario(context: ContextTypes.DEFAULT_TYPE, evento: dict, membro: dict, tipo_agape: str):
    """
    Notifica o secretário que criou o evento sobre uma nova confirmação de presença.
    
    O secretário é determinado pelo campo 'Telegram ID do secretário' do evento.
    Se vazio, nenhuma notificação é enviada (respeita preferência do secretário).
    """
    secretario_id = evento.get("Telegram ID do secretário", "")
    if not secretario_id:
        logger.debug(f"Nenhum secretário definido para o evento")
        return

    try:
        secretario_id = int(float(secretario_id))
    except (ValueError, TypeError):
        logger.warning(f"ID do secretário inválido: {secretario_id}")
        return

    # Verifica se o SECRETÁRIO quer receber notificações
    if not get_notificacao_status(secretario_id):
        logger.debug(f"Secretário {secretario_id} desativou notificações")
        return

    nome_loja = evento.get("Nome da loja", "")
    numero = evento.get("Número da loja", "")
    numero_fmt = f" {numero}" if numero else ""
    data = evento.get("Data do evento", "")
    nome_membro = membro.get("Nome", "")
    texto_participacao = _texto_participacao_agape(tipo_agape)

    texto = (
        f"📢 *NOVA CONFIRMAÇÃO*\n\n"
        f"👤 *Irmão:* {nome_membro}\n"
        f"📅 *Sessão:* {data} - {nome_loja}{numero_fmt}\n"
        f"🍽 {texto_participacao}\n"
    )

    id_evento = normalizar_id_evento(evento)
    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Ver resumo", callback_data=f"resumo_evento|{_encode_cb(id_evento)}"),
            InlineKeyboardButton("👥 Ver lista", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")
        ],
    ])

    try:
        await context.bot.send_message(
            chat_id=secretario_id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=teclado,
        )
        logger.info(f"Notificação enviada ao secretário {secretario_id} sobre nova confirmação em {id_evento}")
    except Exception as e:
        logger.error(f"Erro ao notificar secretário {secretario_id}: {e}")


# ============================================
# FUNÇÕES DE CALENDÁRIO
# ============================================

def gerar_calendario_mes(ano: int, mes: int, eventos: List[dict]) -> str:
    if mes < 1 or mes > 12:
        hoje = datetime.now()
        ano = hoje.year
        mes = hoje.month

    meses_pt = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO"
    }

    cal = calendar.monthcalendar(ano, mes)

    dias_com_evento = set()
    for ev in eventos:
        data_dt = parse_data_evento(ev.get("Data do evento", ""))
        if data_dt and data_dt.year == ano and data_dt.month == mes:
            dias_com_evento.add(data_dt.day)

    linhas = []
    linhas.append(f"📅 *{meses_pt[mes]} {ano}*")
    linhas.append("```")
    linhas.append(" DOM SEG TER QUA QUI SEX SAB")

    for semana in cal:
        linha = ""
        for dia in semana:
            if dia == 0:
                linha += "    "
            else:
                if dia in dias_com_evento:
                    linha += f" {dia:2d}●"
                else:
                    linha += f" {dia:2d} "
        linhas.append(linha)

    linhas.append("```")
    linhas.append("")
    linhas.append(f"Legenda: ● Dias com sessão")
    linhas.append(f"Total de sessões no mês: {len(dias_com_evento)}")

    return "\n".join(linhas)


# ============================================
# HANDLERS PRINCIPAIS
# ============================================

async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Calendário do mês", callback_data="calendario|0|0")],
        [InlineKeyboardButton("📅 Esta semana", callback_data=f"data|{TOKEN_SEMANA_ATUAL}")],
        [InlineKeyboardButton("📅 Próxima semana", callback_data=f"data|{TOKEN_PROXIMA_SEMANA}")],
        [InlineKeyboardButton("📅 Este mês", callback_data=f"data|{TOKEN_MES_ATUAL}")],
        [InlineKeyboardButton("📅 Próximos meses", callback_data=f"data|{TOKEN_PROXIMOS_MESES}")],
        [InlineKeyboardButton("🔺 Por grau", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Ver Sessões",
        "📅 *Como deseja visualizar as sessões?*",
        teclado
    )


async def mostrar_calendario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime

    hoje = datetime.now()
    ano = hoje.year
    mes = hoje.month

    data = update.callback_query.data
    if data.startswith("calendario|"):
        partes = data.split("|")
        if len(partes) >= 3:
            try:
                ano_param = int(partes[1])
                mes_param = int(partes[2])
                if 1 <= mes_param <= 12:
                    ano = ano_param
                    mes = mes_param
            except:
                pass

    eventos = listar_eventos() or []
    calendario = gerar_calendario_mes(ano, mes, eventos)

    mes_ant = mes - 1
    ano_ant = ano
    if mes_ant == 0:
        mes_ant = 12
        ano_ant = ano - 1

    mes_prox = mes + 1
    ano_prox = ano
    if mes_prox == 13:
        mes_prox = 1
        ano_prox = ano + 1

    botoes = [
        [
            InlineKeyboardButton("◀️ Anterior", callback_data=f"calendario|{ano_ant}|{mes_ant}"),
            InlineKeyboardButton("📅 Mês atual", callback_data="calendario_atual"),
            InlineKeyboardButton("Próximo ▶️", callback_data=f"calendario|{ano_prox}|{mes_prox}")
        ],
        [InlineKeyboardButton("📋 Ver sessões do mês", callback_data=f"data|{TOKEN_MES_ATUAL}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")],
    ]

    await navegar_para(
        update, context,
        f"Ver Sessões > Calendário",
        calendario,
        InlineKeyboardMarkup(botoes)
    )


async def calendario_atual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mostrar_calendario(update, context)


async def mostrar_eventos_por_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, token_or_data = query.data.split("|", 1)
    token_or_data = (token_or_data or "").strip()

    if token_or_data == TOKEN_POR_GRAU_MENU:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔺 {GRAU_APRENDIZ}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_APRENDIZ}")],
            [InlineKeyboardButton(f"🔺 {GRAU_COMPANHEIRO}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_COMPANHEIRO}")],
            [InlineKeyboardButton(f"🔺 {GRAU_MESTRE}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_MESTRE}")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")],
        ])
        await navegar_para(
            update, context,
            "Ver Sessões > Por Grau",
            "🔺 *Selecione o grau:*",
            teclado
        )
        return

    eventos = listar_eventos() or []

    if token_or_data in (TOKEN_SEMANA_ATUAL, TOKEN_PROXIMA_SEMANA, TOKEN_MES_ATUAL, TOKEN_PROXIMOS_MESES):
        titulo, filtrados = _filtrar_por_periodo(eventos, token_or_data)

        if not filtrados:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                f"*{titulo}*\n\nNão há sessões agendadas para este período.",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")
                ]])
            )
            return

        filtrados = filtrados[:MAX_EVENTOS_LISTA]
        botoes = []
        for ev in filtrados:
            id_evento = normalizar_id_evento(ev)
            botoes.append([InlineKeyboardButton(
                _linha_botao_evento(ev),
                callback_data=f"evento|{_encode_cb(id_evento)}"
            )])

        botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")])

        await navegar_para(
            update, context,
            f"Ver Sessões > {titulo}",
            f"*{titulo}*\n\nSelecione uma sessão:",
            InlineKeyboardMarkup(botoes)
        )


async def mostrar_eventos_por_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partes = query.data.split("|", 2)
    if len(partes) < 3:
        return

    _, data_or_menu, grau_raw = partes
    grau = normalizar_grau_nome(grau_raw)
    eventos = listar_eventos() or []

    if data_or_menu == TOKEN_POR_GRAU_MENU:
        titulo, filtrados = _filtrar_por_grau(eventos, grau)

        if not filtrados:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                f"*{titulo}*\n\nNão há sessões para este grau no momento.",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")
                ]])
            )
            return

        filtrados = filtrados[:MAX_EVENTOS_LISTA]
        botoes = []
        for ev in filtrados:
            id_evento = normalizar_id_evento(ev)
            botoes.append([InlineKeyboardButton(
                _linha_botao_evento(ev),
                callback_data=f"evento|{_encode_cb(id_evento)}"
            )])

        botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")])

        await navegar_para(
            update, context,
            f"Ver Sessões > Por Grau > {grau}",
            f"*{titulo}*\n\nSelecione uma sessão:",
            InlineKeyboardMarkup(botoes)
        )


# ============================================
# DETALHES DO EVENTO
# ============================================

async def mostrar_detalhes_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Sessão não encontrada ou não está mais ativa.",
            limpar_conteudo=True
        )
        return

    nome = str(evento.get("Nome da loja", "") or "").strip()
    numero = str(evento.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero else ""
    oriente = str(evento.get("Oriente", "") or "").strip()
    potencia = str(evento.get("Potência", "") or "").strip()
    data = evento.get("Data do evento", "")
    hora = str(evento.get("Hora", "") or "").strip()
    tipo_sessao = str(evento.get("Tipo de sessão", "") or "").strip()
    rito = str(evento.get("Rito", "") or "").strip()
    grau = normalizar_grau_nome(str(evento.get("Grau", "") or "").strip())
    traje = str(evento.get("Traje obrigatório", "") or "").strip()
    agape = str(evento.get("Ágape", "") or "").strip()
    obs = str(evento.get("Observações", "") or "").strip()
    endereco_raw = str(evento.get("Endereço da sessão", "") or "").strip()

    data_obj = parse_data_evento(data)
    if data_obj:
        dia_semana = traduzir_dia(data_obj.strftime("%A"))
        data_formatada = f"{data_obj.strftime('%d/%m/%Y')} ({dia_semana})"
    else:
        data_formatada = str(data or "").strip()

    texto = (
        f"🏛 *LOJA {nome}{numero_fmt}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📍 *Oriente:* {oriente}\n"
        f"⚜️ *Potência:* {potencia}\n"
        f"📅 *Data:* {data_formatada}\n"
        f"🕕 *Horário:* {hora}\n"
        f"🕯 *Tipo:* {tipo_sessao}\n"
        f"📜 *Rito:* {rito}\n"
        f"🔺 *Grau mínimo:* {grau}\n"
        f"👔 *Traje:* {traje}\n"
        f"🍽 *Ágape:* {agape}\n"
    )

    botoes_extras = []
    if endereco_raw:
        if endereco_raw.startswith(("http://", "https://")):
            texto += f"\n📍 *Link do local:* [Clique aqui]({endereco_raw})"
            botoes_extras.append([InlineKeyboardButton("📍 Abrir no mapa", url=endereco_raw)])
        else:
            texto += f"\n📍 *Endereço:* {endereco_raw}"
    else:
        texto += "\n📍 *Endereço:* Não informado"

    if obs:
        texto += f"\n\n📌 *Observações:* {obs}"

    user_id = update.effective_user.id
    ja_confirmou = buscar_confirmacao(id_evento, user_id)
    botoes = []

    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    else:
        botoes.extend(_teclado_confirmacao_evento(id_evento, agape))

    botoes.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")])
    
    if botoes_extras:
        botoes.extend(botoes_extras)
    
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")])

    await navegar_para(
        update, context,
        f"Ver Sessões > {nome}",
        texto,
        InlineKeyboardMarkup(botoes)
    )


# ============================================
# CONFIRMAÇÃO DE PRESENÇA
# ============================================

async def iniciar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partes = query.data.split("|")
    if len(partes) < 3:
        return ConversationHandler.END

    _, id_evento_cod, tipo_agape = partes
    id_evento = _decode_cb(id_evento_cod)
    user_id = update.effective_user.id

    # Paralelizar buscas para reduzir latência
    import asyncio
    
    def buscar_eventos_sync():
        eventos = listar_eventos() or []
        return next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    
    def buscar_membro_sync():
        return buscar_membro(user_id)
    
    evento, membro = await asyncio.gather(
        asyncio.to_thread(buscar_eventos_sync),
        asyncio.to_thread(buscar_membro_sync)
    )

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Sessão não encontrada ou não está mais ativa.",
            limpar_conteudo=True
        )
        return ConversationHandler.END

    if not membro:
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "id_evento": id_evento,
            "tipo_agape": tipo_agape
        }
        teclado = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Fazer cadastro", callback_data="iniciar_cadastro")]])
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Irmão, antes de confirmar sua presença, preciso registrar seu cadastro.",
            teclado,
            limpar_conteudo=True
        )
        return ConversationHandler.END

    # Verificar confirmação existente (agora cacheada)
    if buscar_confirmacao(id_evento, user_id):
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Você já confirmou presença para esta sessão.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")
            ]]),
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await query.answer("Você já confirmou. Verifique seu privado.")
        return ConversationHandler.END

    participacao_agape = "Confirmada" if tipo_agape != "sem" else "Não"
    confirmou_com_agape = tipo_agape != "sem"
    desc_agape = {
        "gratuito": "Gratuito",
        "pago": "Pago",
        "com": "Com ágape",
    }.get(tipo_agape, "Não aplicável")
    texto_participacao = _texto_participacao_agape(tipo_agape)

    dados_confirmacao = {
        "id_evento": id_evento,
        "telegram_id": str(user_id),
        "nome": membro.get("Nome", ""),
        "grau": normalizar_grau_nome(membro.get("Grau", "")),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "numero_loja": membro.get("Número da loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "agape": f"{participacao_agape} ({desc_agape})",
        "veneravel_mestre": membro.get("Venerável Mestre", ""),
    }
    registrar_confirmacao(dados_confirmacao)

    # Verificar se o usuário é o secretário do evento
    secretario_id = evento.get("Telegram ID do secretário", "")
    try:
        secretario_id = int(float(secretario_id))
    except:
        secretario_id = None
    
    eh_secretario = secretario_id == user_id

    # Notificar secretário apenas se não for o próprio usuário
    if not eh_secretario:
        await notificar_secretario(context, evento, membro, tipo_agape)

    data = str(evento.get("Data do evento", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    numero_loja = str(evento.get("Número da loja", "") or "").strip()
    horario = str(evento.get("Hora", "") or "").strip()
    numero_fmt = f" {numero_loja}" if numero_loja else ""

    bloco_importancia = f"{MENSAGEM_CONFIRMACAO_AGAPE}\n\n" if confirmou_com_agape else ""

    if eh_secretario:
        # Mensagem combinada para secretário
        resposta = (
            f"✅ *Presença confirmada, irmão {membro.get('Nome', '')}!*\n\n"
            f"Resumo:\n"
            f"📅 {data} — {nome_loja}{numero_fmt}\n"
            f"🕕 Horário: {horario}\n"
            f"🍽 {texto_participacao}\n\n"
            f"{bloco_importancia}"
            f"📢 *Nova confirmação registrada*"
        )
        
        teclado = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Ver resumo", callback_data=f"resumo_evento|{_encode_cb(id_evento)}"),
                InlineKeyboardButton("👥 Ver lista", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")
            ],
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
        ])
    else:
        # Mensagem normal para usuário comum
        if confirmou_com_agape:
            resposta = (
                f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
                f"Resumo:\n"
                f"📅 {data} — {nome_loja}{numero_fmt}\n"
                f"🕕 Horário: {horario}\n"
                f"🍽 {texto_participacao}\n\n"
                f"{MENSAGEM_CONFIRMACAO_AGAPE}\n\n"
                "Até lá!"
            )
        else:
            resposta = (
                f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
                f"Resumo:\n"
                f"📅 {data} — {nome_loja}{numero_fmt}\n"
                f"🕕 Horário: {horario}\n"
                f"🍽 {texto_participacao}\n\n"
                "Até lá!"
            )

        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
        ])

    await context.bot.send_message(
        chat_id=user_id,
        text=resposta,
        parse_mode="Markdown",
        reply_markup=teclado
    )
    await enviar_dica_contextual(update, context, "confirmacao_presenca")

    if update.effective_chat.type in ["group", "supergroup"]:
        await query.answer("✅ Presença confirmada! Verifique seu privado.")

    return ConversationHandler.END


# Função auxiliar para continuar confirmação após cadastro
async def iniciar_confirmacao_presenca_pos_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE, pos: dict):
    user_id = update.effective_user.id
    id_evento = pos.get("id_evento")
    tipo_agape = pos.get("tipo_agape", "sem")

    if not id_evento:
        return

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await context.bot.send_message(
            chat_id=user_id,
            text="Sessão não encontrada. Tente confirmar novamente."
        )
        return

    membro = buscar_membro(user_id)
    if not membro:
        return

    if buscar_confirmacao(id_evento, user_id):
        await context.bot.send_message(
            chat_id=user_id,
            text="Você já estava confirmado para esta sessão.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
                [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
            ])
        )
        return

    participacao_agape = "Confirmada" if tipo_agape != "sem" else "Não"
    confirmou_com_agape = tipo_agape != "sem"
    desc_agape = {
        "gratuito": "Gratuito",
        "pago": "Pago",
        "com": "Com ágape",
    }.get(tipo_agape, "Não aplicável")
    texto_participacao = _texto_participacao_agape(tipo_agape)

    dados_confirmacao = {
        "id_evento": id_evento,
        "telegram_id": str(user_id),
        "nome": membro.get("Nome", ""),
        "grau": normalizar_grau_nome(membro.get("Grau", "")),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "numero_loja": membro.get("Número da loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "agape": f"{participacao_agape} ({desc_agape})",
        "veneravel_mestre": membro.get("Venerável Mestre", ""),
    }
    registrar_confirmacao(dados_confirmacao)

    await notificar_secretario(context, evento, membro, tipo_agape)

    data = str(evento.get("Data do evento", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    numero_loja = str(evento.get("Número da loja", "") or "").strip()
    horario = str(evento.get("Hora", "") or "").strip()
    numero_fmt = f" {numero_loja}" if numero_loja else ""

    if confirmou_com_agape:
        resposta = (
            f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
            f"Resumo:\n"
            f"📅 {data} — {nome_loja}{numero_fmt}\n"
            f"🕕 Horário: {horario}\n"
            f"🍽 {texto_participacao}\n\n"
            f"{MENSAGEM_CONFIRMACAO_AGAPE}\n\n"
            "Até lá!"
        )
    else:
        resposta = (
            f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
            f"Resumo:\n"
            f"📅 {data} — {nome_loja}{numero_fmt}\n"
            f"🕕 Horário: {horario}\n"
            f"🍽 {texto_participacao}\n\n"
            "Até lá!"
        )

    await context.bot.send_message(
        chat_id=user_id,
        text=resposta,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
        ])
    )
    await enviar_dica_contextual(update, context, "confirmacao_presenca")


# ============================================
# CANCELAMENTO DE PRESENÇA (CORRIGIDO COM IMPORTAÇÕES)
# ============================================

async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa o cancelamento de presença."""
    query = update.callback_query
    data = query.data

    # CASO 1: Confirmação de cancelamento (passo 2)
    if data.startswith("confirma_cancelar|"):
        _, id_evento_cod = data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        logger.info(f"Processando confirmação de cancelamento: evento {id_evento}, usuário {user_id}")

        if cancelar_confirmacao(id_evento, user_id):
            # Feedback visual IMEDIATO
            if update.effective_chat.type in ["group", "supergroup"]:
                # No grupo: apaga a lista e mostra mensagem de confirmação
                try:
                    await query.delete_message()
                except Exception as e:
                    logger.error(f"Erro ao deletar mensagem: {e}")
                
                # Envia mensagem de confirmação no grupo
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="✅ *Presença cancelada com sucesso!*",
                    parse_mode="Markdown"
                )
            else:
                # No privado: edita a mensagem com confirmação
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    "❌ *Presença cancelada*\n\nSe mudar de ideia, sua confirmação será bem-vinda.",
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
                    ]),
                    limpar_conteudo=True
                )
            await query.answer("✅ Presença cancelada!")
        else:
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "Não foi possível cancelar. Você não estava confirmado para esta sessão.",
                limpar_conteudo=True
            )
        return

    # CASO 2: Pedido de cancelamento (passo 1)
    if data.startswith("cancelar|"):
        _, id_evento_cod = data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        logger.info(f"Processando pedido de cancelamento: evento {id_evento}, usuário {user_id}")

        # Se estiver em grupo, redireciona para o privado para confirmação
        if update.effective_chat.type in ["group", "supergroup"]:
            teclado = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar|{_encode_cb(id_evento)}"),
                InlineKeyboardButton("🔙 Não, voltar", callback_data=f"evento|{_encode_cb(id_evento)}")
            ]])
            await context.bot.send_message(
                chat_id=user_id,
                text="*Confirmar cancelamento da sua presença?*",
                parse_mode="Markdown",
                reply_markup=teclado
            )
            await query.answer("📨 Instruções enviadas no privado.")
            return

        # Se estiver no privado, já pode cancelar direto
        if cancelar_confirmacao(id_evento, user_id):
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "❌ *Presença cancelada*\n\nSe mudar de ideia, sua confirmação será bem-vinda.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
                ]),
                limpar_conteudo=True
            )
        else:
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "Não foi possível cancelar. Você não estava confirmado para esta sessão.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
                ]),
                limpar_conteudo=True
            )
        return

    await _enviar_ou_editar_mensagem(
        context, update.effective_user.id, TIPO_RESULTADO,
        "Comando de cancelamento inválido.",
        limpar_conteudo=True
    )


# ============================================
# LISTA DE CONFIRMADOS
# ============================================

async def ver_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("👥 Buscando lista de confirmados...")

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        titulo = "CONFIRMADOS"
        data_evento = ""
        nome_loja = ""
    else:
        nome_loja = str(evento.get("Nome da loja", "") or "").strip()
        data_evento = str(evento.get("Data do evento", "") or "").strip()
        titulo = f"CONFIRMADOS - {nome_loja}"

    confirmacoes = listar_confirmacoes_por_evento(id_evento) or []

    linhas: List[str] = []
    for c in confirmacoes:
        tid = _tid_to_int(c.get("Telegram ID") or c.get("telegram_id"))
        membro = buscar_membro(tid) if tid is not None else None

        if membro:
            linhas.append(montar_linha_confirmado(membro))
        else:
            snapshot = {
                "Grau": c.get("Grau", c.get("grau", "")),
                "Nome": c.get("Nome", c.get("nome", "")),
                "Loja": c.get("Loja", c.get("loja", "")),
                "Número da loja": c.get("Número da loja", c.get("numero_loja", "")),
                "Oriente": c.get("Oriente", c.get("oriente", "")),
                "Potência": c.get("Potência", c.get("potencia", "")),
                "Venerável Mestre": c.get("Venerável Mestre", c.get("veneravel_mestre", "")),
            }
            linhas.append(montar_linha_confirmado(snapshot))

    corpo = "Nenhuma presença confirmada até o momento." if not linhas else "\n".join(linhas)
    texto = f"*{titulo}*\n{data_evento}\n\n{corpo}"

    user_id = update.effective_user.id
    ja_confirmou = buscar_confirmacao(id_evento, user_id)

    botoes = []
    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    else:
        agape_evento = str((evento or {}).get("Ágape", "") or "")
        botoes.extend(_teclado_confirmacao_evento(id_evento, agape_evento))

    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])

    # COMPORTAMENTO ORIGINAL: SEMPRE envia nova mensagem
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


# ============================================
# MINHAS CONFIRMAÇÕES
# ============================================

async def minhas_confirmacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Próximas sessões", callback_data="minhas_confirmacoes_futuro")],
        [InlineKeyboardButton("📜 Histórico", callback_data="minhas_confirmacoes_historico")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Minhas Presenças",
        "📌 *Suas confirmações*\n\nEscolha o que deseja ver:",
        teclado
    )


async def minhas_confirmacoes_futuro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    eventos = listar_eventos() or []
    eventos = _eventos_ordenados(eventos)

    hoje = datetime.now().date()

    confirmados = []
    for ev in eventos:
        id_evento = normalizar_id_evento(ev)
        if buscar_confirmacao(id_evento, user_id):
            data_str = ev.get("Data do evento", "")
            try:
                data_evento = datetime.strptime(data_str, "%d/%m/%Y").date()
                if data_evento >= hoje:
                    confirmados.append(ev)
            except:
                confirmados.append(ev)

    if not confirmados:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "📅 *Próximas sessões*\n\nVocê não possui confirmações para as próximas sessões.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmacoes")
            ]]),
            limpar_conteudo=True
        )
        return

    botoes = []
    for ev in confirmados[:MAX_EVENTOS_LISTA]:
        id_evento = normalizar_id_evento(ev)
        label = _linha_botao_evento(ev)
        botoes.append([InlineKeyboardButton(label, callback_data=f"detalhes_confirmado|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmacoes")])

    await navegar_para(
        update, context,
        "Minhas Presenças > Próximas",
        "📅 *Próximas sessões*\n\nSelecione para ver detalhes:",
        InlineKeyboardMarkup(botoes)
    )


async def minhas_confirmacoes_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    eventos = listar_eventos() or []
    eventos = _eventos_ordenados(eventos)

    hoje = datetime.now().date()

    confirmados = []
    for ev in eventos:
        id_evento = normalizar_id_evento(ev)
        if buscar_confirmacao(id_evento, user_id):
            data_str = ev.get("Data do evento", "")
            try:
                data_evento = datetime.strptime(data_str, "%d/%m/%Y").date()
                if data_evento < hoje:
                    confirmados.append(ev)
            except:
                continue

    if not confirmados:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "📜 *Histórico*\n\nVocê ainda não participou de nenhuma sessão.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmacoes")
            ]]),
            limpar_conteudo=True
        )
        return

    botoes = []
    for ev in confirmados[:MAX_EVENTOS_LISTA]:
        id_evento = normalizar_id_evento(ev)
        label = _linha_botao_evento(ev)
        botoes.append([InlineKeyboardButton(label, callback_data=f"detalhes_historico|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmacoes")])

    await navegar_para(
        update, context,
        "Minhas Presenças > Histórico",
        "📜 *Histórico*\n\nSessões que você participou:",
        InlineKeyboardMarkup(botoes)
    )


async def detalhes_confirmado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Sessão não encontrada.",
            limpar_conteudo=True
        )
        return

    nome = str(evento.get("Nome da loja", "") or "").strip()
    numero = str(evento.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero else ""
    data_txt = str(evento.get("Data do evento", "") or "").strip()
    hora = str(evento.get("Hora", "") or "").strip()
    oriente = str(evento.get("Oriente", "") or "").strip()
    potencia = str(evento.get("Potência", "") or "").strip()

    user_id = update.effective_user.id
    confirmacao = buscar_confirmacao(id_evento, user_id)
    agape_info = ""
    if confirmacao:
        agape = confirmacao.get("Ágape", "")
        if agape:
            agape_info = f"\n🍽 *Ágape:* {agape}"

    texto = (
        f"🏛 *{nome}{numero_fmt}*\n"
        f"📅 {data_txt}\n"
        f"🕕 {hora}\n"
        f"📍 {oriente}\n"
        f"⚜️ {potencia}{agape_info}"
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmacoes_futuro")],
    ])

    await navegar_para(
        update, context,
        f"Minhas Presenças > {nome}",
        texto,
        teclado
    )


async def detalhes_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Sessão não encontrada.",
            limpar_conteudo=True
        )
        return

    nome = str(evento.get("Nome da loja", "") or "").strip()
    numero = str(evento.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero else ""
    data_txt = str(evento.get("Data do evento", "") or "").strip()
    hora = str(evento.get("Hora", "") or "").strip()
    oriente = str(evento.get("Oriente", "") or "").strip()
    potencia = str(evento.get("Potência", "") or "").strip()

    user_id = update.effective_user.id
    confirmacao = buscar_confirmacao(id_evento, user_id)
    agape_info = ""
    if confirmacao:
        agape = confirmacao.get("Ágape", "")
        if agape:
            agape_info = f"\n🍽 *Ágape:* {agape}"

    texto = (
        f"🏛 *{nome}{numero_fmt}*\n"
        f"📅 {data_txt}\n"
        f"🕕 {hora}\n"
        f"📍 {oriente}\n"
        f"⚜️ {potencia}{agape_info}\n\n"
        "_Esta sessão já aconteceu._"
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmacoes_historico")],
    ])

    await navegar_para(
        update, context,
        f"Histórico > {nome}",
        texto,
        teclado
    )


# ============================================
# FECHAR MENSAGEM (PARA A LISTA DE CONFIRMADOS)
# ============================================

async def fechar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    try:
        await query.delete_message()
    except Exception:
        try:
            await query.edit_message_text("🔒 Fechado.")
        except Exception:
            pass


# ============================================
# CONVERSATION HANDLER
# ============================================

confirmacao_presenca_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmacao_presenca, pattern=r"^confirmar\|")],
    states={},
    fallbacks=[CommandHandler("cancelar", cancelar_presenca)],
)