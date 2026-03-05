# src/eventos.py
from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional, Tuple, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
)

from src.sheets import (
    listar_eventos,
    buscar_membro,
    registrar_confirmacao,
    cancelar_confirmacao,
    buscar_confirmacao,
    listar_confirmacoes_por_evento,
    get_notificacao_status,
)

logger = logging.getLogger(__name__)

# -------------------------
# Config (ajustável)
# -------------------------
MAX_EVENTOS_LISTA = 40  # evita estourar limite de botões do Telegram
MESES_PROXIMOS_QTD = 6  # "Próximos meses" = próximos N meses contando a partir de hoje

# Tokens de filtro
TOKEN_SEMANA_ATUAL = "semana_atual"
TOKEN_PROXIMA_SEMANA = "proxima_semana"
TOKEN_MES_ATUAL = "mes_atual"
TOKEN_PROXIMOS_MESES = "proximos_meses"
TOKEN_POR_GRAU_MENU = "por_grau"

GRAU_APRENDIZ = "Aprendiz"
GRAU_COMPANHEIRO = "Companheiro"
GRAU_MESTRE = "Mestre"

DIAS_SEMANA = {
    "Monday": "Segunda-feira",
    "Tuesday": "Terça-feira",
    "Wednesday": "Quarta-feira",
    "Thursday": "Quinta-feira",
    "Friday": "Sexta-feira",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}


# -------------------------
# Helpers
# -------------------------
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
    return "sem"


def normalizar_grau_nome(valor: str) -> str:
    v = (valor or "").strip().lower()

    # compatibilidade com planilhas antigas / abreviações
    if v in ("todos", "todo", "t", "am", "apr", "aprendiz"):
        return GRAU_APRENDIZ
    if v in ("comp", "companheiro", "c"):
        return GRAU_COMPANHEIRO
    if v in ("mest", "mestre", "m"):
        return GRAU_MESTRE
    if v in ("mi", "mestre instalado", "instalado", "mestreinstalado"):
        return "Mestre Instalado"

    # Se já vier "bonito", preserva
    return (valor or "").strip()


def parse_data_evento(valor: Any) -> Optional[datetime]:
    """
    Converte diferentes formatos de data para datetime.
    Formatos aceitos:
      - dd/mm/aaaa
      - dd/mm/aaaa HH:MM:SS
      - aaaa-mm-dd
      - aaaa-mm-dd HH:MM:SS
      - dd-mm-aaaa
      - datetime/date
    """
    if valor is None:
        return None

    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)

    texto = str(valor).strip()
    if not texto:
        return None

    # Lista de formatos tentativos (do mais específico para o mais genérico)
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
    """
    Converte 'HH:MM' / 'HH:MM:SS' em (HH, MM).
    Se inválido, retorna (99, 99).
    """
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
    """
    Chave do evento (retrocompatível):
      - Preferência: coluna 'ID Evento'
      - Fallback: legado "Data do evento — Nome da loja"
    """
    id_planilha = str(ev.get("ID Evento", "")).strip()
    if id_planilha and id_planilha.lower() != "nan":
        return id_planilha
    return f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"


def _tid_to_int(value: Any) -> Optional[int]:
    """
    Converte Telegram ID vindo de planilha (int/float/str/"123.0") para int.
    """
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
    """
    Lê a coluna 'Venerável Mestre' (ou variações) e interpreta como boolean.
    """
    for k in ("Venerável Mestre", "Veneravel Mestre", "veneravel_mestre", "vm"):
        if k in dados:
            raw = str(dados.get(k) or "").strip().lower()
            return raw in ("sim", "s", "yes", "y", "1", "true")
    return False


def montar_linha_confirmado(dados_membro_ou_snapshot: dict) -> str:
    """
    Formato final (UX):
      {Nome com tratamento opcional} - {GrauNome} - {Loja} {Numero} - {Oriente} - {Potência}

    - Se Venerável Mestre = Sim -> prefixa "VM " no nome
    - Grau é normalizado (am/mest/todos etc.)
    """
    nome = (dados_membro_ou_snapshot.get("Nome") or dados_membro_ou_snapshot.get("nome") or "").strip()
    if _eh_vm(dados_membro_ou_snapshot) and nome:
        nome = f"VM {nome}"

    grau_raw = (dados_membro_ou_snapshot.get("Grau") or dados_membro_ou_snapshot.get("grau") or "").strip()
    grau = normalizar_grau_nome(grau_raw)

    loja = (dados_membro_ou_snapshot.get("Loja") or dados_membro_ou_snapshot.get("loja") or "").strip()
    numero = (
        (dados_membro_ou_snapshot.get("Número da loja") or dados_membro_ou_snapshot.get("numero_loja") or "")
    )
    numero = str(numero).strip()

    oriente = (dados_membro_ou_snapshot.get("Oriente") or dados_membro_ou_snapshot.get("oriente") or "").strip()
    potencia = (dados_membro_ou_snapshot.get("Potência") or dados_membro_ou_snapshot.get("potencia") or "").strip()

    loja_composta = f"{loja} {numero}".strip()
    return f"{nome} - {grau} - {loja_composta} - {oriente} - {potencia}"


def _data_range_semana(ref: date) -> Tuple[date, date]:
    # semana = segunda..domingo
    start = ref - timedelta(days=ref.weekday())
    end = start + timedelta(days=6)
    return start, end


def _ultimo_dia_mes(ano: int, mes: int) -> date:
    if mes == 12:
        return date(ano, 12, 31)
    primeiro_prox = date(ano, mes + 1, 1)
    return primeiro_prox - timedelta(days=1)


def _add_months(d: date, months: int) -> date:
    # simples e suficiente para ranges (leva para o 1º dia do mês resultante)
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
        # eventos sem data/hora vão para o final
        dt = self.data_dt or datetime(2100, 1, 1)
        hh, mm = self.hora_tuple
        return (dt.date(), hh, mm, normalizar_id_evento(self.evento))


def _eventos_ordenados(eventos: List[dict]) -> List[dict]:
    tmp: List[EventoOrdenavel] = []
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
        titulo = "Eventos — Esta semana"
    elif token == TOKEN_PROXIMA_SEMANA:
        ini0, fim0 = _data_range_semana(hoje)
        ini = ini0 + timedelta(days=7)
        fim = fim0 + timedelta(days=7)
        titulo = "Eventos — Próxima semana"
    elif token == TOKEN_MES_ATUAL:
        ini = date(hoje.year, hoje.month, 1)
        fim = _ultimo_dia_mes(hoje.year, hoje.month)
        titulo = "Eventos — Este mês"
    elif token == TOKEN_PROXIMOS_MESES:
        ini = hoje
        ini_mes_atual = date(hoje.year, hoje.month, 1)
        limite_inicio = _add_months(ini_mes_atual, MESES_PROXIMOS_QTD)
        fim = _ultimo_dia_mes(limite_inicio.year, limite_inicio.month)
        titulo = "Eventos — Próximos meses"
    else:
        return "Eventos", []

    filtrados: List[dict] = []
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
    titulo = f"Eventos — Grau — {alvo}".strip()

    filtrados: List[dict] = []
    for ev in eventos:
        g = normalizar_grau_nome(str(ev.get("Grau") or "").strip())
        if g == alvo:
            filtrados.append(ev)

    return titulo, _eventos_ordenados(filtrados)


def _formatar_data_curta(ev: dict) -> str:
    dt = parse_data_evento(ev.get("Data do evento", ""))
    if not dt:
        data_txt = str(ev.get("Data do evento", "") or "").strip()
        return data_txt or "Sem data"
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


async def _safe_edit(query, text: str, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


# -------------------------
# Função para notificar secretário
# -------------------------
async def notificar_secretario(context: ContextTypes.DEFAULT_TYPE, evento: dict, membro: dict, tipo_agape: str, desc_agape: str):
    """Envia notificação para o secretário sobre nova confirmação (se ele tiver ativo)."""
    secretario_id = evento.get("Telegram ID do secretário", "")
    if not secretario_id:
        return

    try:
        secretario_id = int(float(secretario_id))
    except:
        return

    # Verifica se o secretário tem notificações ativas na planilha
    if not get_notificacao_status(secretario_id):
        return  # Secretário optou por não receber notificações

    nome_loja = evento.get("Nome da loja", "")
    numero = evento.get("Número da loja", "")
    numero_fmt = f" {numero}" if numero else ""
    data = evento.get("Data do evento", "")
    nome_membro = membro.get("Nome", "")

    texto = (
        f"📢 *NOVA CONFIRMAÇÃO*\n\n"
        f"👤 *Irmão:* {nome_membro}\n"
        f"📅 *Evento:* {data} - {nome_loja}{numero_fmt}\n"
        f"🍽 *Ágape:* {tipo_agape} ({desc_agape})\n"
    )

    # Criar botões para ações rápidas
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
    except Exception as e:
        logger.error(f"Erro ao notificar secretário {secretario_id}: {e}")


# -------------------------
# Função para gerar calendário visual
# -------------------------
def gerar_calendario_mes(ano: int, mes: int, eventos: List[dict]) -> str:
    """
    Gera um calendário visual do mês com marcações nos dias que têm evento.
    """
    import calendar
    from datetime import datetime
    
    # Validação de mês e ano
    if mes < 1 or mes > 12:
        # Se mês inválido, usa mês atual
        hoje = datetime.now()
        ano = hoje.year
        mes = hoje.month
    
    # Nomes dos meses em português
    meses_pt = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO"
    }
    
    # Cria um calendário
    cal = calendar.monthcalendar(ano, mes)
    
    # Identifica quais dias têm evento
    dias_com_evento = set()
    for ev in eventos:
        data_dt = parse_data_evento(ev.get("Data do evento", ""))
        if data_dt and data_dt.year == ano and data_dt.month == mes:
            dias_com_evento.add(data_dt.day)
    
    # Cabeçalho
    linhas = []
    linhas.append(f"📅 *{meses_pt[mes]} {ano}*")
    linhas.append("```")
    linhas.append(" DOM SEG TER QUA QUI SEX SAB")
    
    # Para cada semana do mês
    for semana in cal:
        linha = ""
        for dia in semana:
            if dia == 0:
                linha += "    "  # Espaço para dias fora do mês
            else:
                if dia in dias_com_evento:
                    # Dia com evento - formata com 2 dígitos e marcador
                    linha += f" {dia:2d}●"
                else:
                    # Dia sem evento
                    linha += f" {dia:2d} "
        linhas.append(linha)
    
    linhas.append("```")
    linhas.append("")
    linhas.append(f"Legenda: ● Dias com evento")
    linhas.append(f"Total de eventos no mês: {len(dias_com_evento)}")
    
    return "\n".join(linhas)


# -------------------------
# 1) 📅 Ver eventos (novo padrão) -> menu com 6 botões
# -------------------------
async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("📅 Carregando opções...")

    teclado = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Calendário do mês", callback_data="calendario|0|0")],
            [InlineKeyboardButton("Esta semana", callback_data=f"data|{TOKEN_SEMANA_ATUAL}")],
            [InlineKeyboardButton("Próxima semana", callback_data=f"data|{TOKEN_PROXIMA_SEMANA}")],
            [InlineKeyboardButton("Este mês", callback_data=f"data|{TOKEN_MES_ATUAL}")],
            [InlineKeyboardButton("Próximos meses", callback_data=f"data|{TOKEN_PROXIMOS_MESES}")],
            [InlineKeyboardButton("Por grau", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")],
            [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
        ]
    )

    await _safe_edit(query, "📅 *Ver eventos*\n\nEscolha um atalho:", parse_mode="Markdown", reply_markup=teclado)


# -------------------------
# 2) Handler: data|...
# -------------------------
async def mostrar_eventos_por_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("📅 Filtrando eventos...")

    _, token_or_data = query.data.split("|", 1)
    token_or_data = (token_or_data or "").strip()

    # Submenu: Por Grau (abre 3 botões)
    if token_or_data == TOKEN_POR_GRAU_MENU:
        teclado = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(f"🔺 {GRAU_APRENDIZ}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_APRENDIZ}")],
                [InlineKeyboardButton(f"🔺 {GRAU_COMPANHEIRO}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_COMPANHEIRO}")],
                [InlineKeyboardButton(f"🔺 {GRAU_MESTRE}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_MESTRE}")],
                [InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]
        )
        await _safe_edit(query, "🔺 *Filtrar por grau*\n\nEscolha o grau:", parse_mode="Markdown", reply_markup=teclado)
        return

    eventos = listar_eventos() or []

    # Tokens de período (novo padrão)
    if token_or_data in (TOKEN_SEMANA_ATUAL, TOKEN_PROXIMA_SEMANA, TOKEN_MES_ATUAL, TOKEN_PROXIMOS_MESES):
        titulo, filtrados = _filtrar_por_periodo(eventos, token_or_data)

        if not filtrados:
            teclado = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")],
                    [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
                ]
            )
            await _safe_edit(
                query,
                f"*{titulo}*\n\nNão existem sessões disponíveis para este filtro no momento.",
                parse_mode="Markdown",
                reply_markup=teclado,
            )
            return

        filtrados = filtrados[:MAX_EVENTOS_LISTA]
        botoes = []
        for ev in filtrados:
            id_evento = normalizar_id_evento(ev)
            botoes.append([InlineKeyboardButton(_linha_botao_evento(ev), callback_data=f"evento|{_encode_cb(id_evento)}")])

        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")])
        botoes.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])

        await _safe_edit(
            query,
            f"*{titulo}*\n\nSelecione um evento:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes),
        )
        return

    # Compatibilidade: token_or_data pode ser uma data real dd/mm/aaaa (fluxo antigo)
    eventos_data = [e for e in eventos if str(e.get("Data do evento", "")).strip() == token_or_data]

    if not eventos_data:
        teclado = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]
        )
        await _safe_edit(query, "Não existem sessões disponíveis para esta data no momento.", reply_markup=teclado)
        return

    # Fluxo antigo: agrupar por grau
    graus: Dict[str, List[dict]] = {}
    for evento in eventos_data:
        grau = normalizar_grau_nome(str(evento.get("Grau", "Indefinido")))
        graus.setdefault(grau, []).append(evento)

    botoes = []
    for grau, evs in graus.items():
        botoes.append([InlineKeyboardButton(f"🔺 {grau} - {len(evs)} evento(s)", callback_data=f"grau|{token_or_data}|{grau}")])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")])
    botoes.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])

    await _safe_edit(
        query,
        f"📅 *{token_or_data}*\n\nSelecione o grau:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


# -------------------------
# 3) Handler: grau|{data_ou_menu}|{grau}
# -------------------------
async def mostrar_eventos_por_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("🔺 Filtrando por grau...")

    partes = query.data.split("|", 2)
    if len(partes) < 3:
        await _safe_edit(query, "Filtro inválido.")
        return

    _, data_or_menu, grau_raw = partes
    grau = normalizar_grau_nome(grau_raw)

    eventos = listar_eventos() or []

    # Novo fluxo: Por grau (sem data)
    if data_or_menu == TOKEN_POR_GRAU_MENU:
        titulo, filtrados = _filtrar_por_grau(eventos, grau)

        if not filtrados:
            teclado = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⬅️ Voltar", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")],
                    [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
                ]
            )
            await _safe_edit(
                query,
                f"*{titulo}*\n\nNão existem sessões disponíveis para este grau no momento.",
                parse_mode="Markdown",
                reply_markup=teclado,
            )
            return

        filtrados = filtrados[:MAX_EVENTOS_LISTA]
        botoes = []
        for ev in filtrados:
            id_evento = normalizar_id_evento(ev)
            botoes.append([InlineKeyboardButton(_linha_botao_evento(ev), callback_data=f"evento|{_encode_cb(id_evento)}")])

        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")])
        botoes.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])

        await _safe_edit(
            query,
            f"*{titulo}*\n\nSelecione um evento:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes),
        )
        return

    # Fluxo antigo: data + grau
    eventos_filtrados = [
        e for e in eventos
        if str(e.get("Data do evento", "")).strip() == str(data_or_menu).strip()
        and normalizar_grau_nome(str(e.get("Grau", "")).strip()) == grau
    ]
    eventos_filtrados = _eventos_ordenados(eventos_filtrados)

    if not eventos_filtrados:
        teclado = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ Voltar", callback_data=f"data|{data_or_menu}")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]
        )
        await _safe_edit(query, "Não existem sessões disponíveis para este filtro no momento.", reply_markup=teclado)
        return

    botoes = []
    for ev in eventos_filtrados[:MAX_EVENTOS_LISTA]:
        id_evento = normalizar_id_evento(ev)
        botoes.append([InlineKeyboardButton(_linha_botao_evento(ev), callback_data=f"evento|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"data|{data_or_menu}")])
    botoes.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])

    await _safe_edit(
        query,
        f"🔺 *{grau}*\n\nSelecione um evento:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


# -------------------------
# 4) Handler para mostrar calendário
# -------------------------
async def mostrar_calendario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra um calendário visual do mês atual com os eventos."""
    query = update.callback_query
    if not query:
        return
    await query.answer("📅 Gerando calendário...")

    from datetime import datetime
    
    # Pega mês e ano atuais (padrão)
    hoje = datetime.now()
    ano = hoje.year
    mes = hoje.month
    
    # Se veio com parâmetro para navegar entre meses
    data = query.data
    if data.startswith("calendario|"):
        partes = data.split("|")
        if len(partes) >= 3:
            try:
                ano_param = int(partes[1])
                mes_param = int(partes[2])
                # Só atualiza se mês estiver entre 1 e 12
                if 1 <= mes_param <= 12:
                    ano = ano_param
                    mes = mes_param
            except:
                pass  # Se erro, mantém mês atual
    
    eventos = listar_eventos() or []
    
    # Gera o calendário
    calendario = gerar_calendario_mes(ano, mes, eventos)
    
    # Botões de navegação entre meses
    from calendar import monthrange
    
    # Mês anterior
    mes_ant = mes - 1
    ano_ant = ano
    if mes_ant == 0:
        mes_ant = 12
        ano_ant = ano - 1
    
    # Mês seguinte
    mes_prox = mes + 1
    ano_prox = ano
    if mes_prox == 13:
        mes_prox = 1
        ano_prox = ano + 1
    
    botoes = [
        [
            InlineKeyboardButton("◀️ Anterior", callback_data=f"calendario|{ano_ant}|{mes_ant}"),
            InlineKeyboardButton("Mês atual", callback_data="calendario_atual"),
            InlineKeyboardButton("Próximo ▶️", callback_data=f"calendario|{ano_prox}|{mes_prox}")
        ],
        [InlineKeyboardButton("📅 Ver eventos do mês", callback_data=f"data|{TOKEN_MES_ATUAL}")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")],
        [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
    ]
    
    await _safe_edit(
        query,
        calendario,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def calendario_atual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Volta para o calendário do mês atual."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    from datetime import datetime
    hoje = datetime.now()
    # Chama o calendário com o mês atual
    await mostrar_calendario(update, context)


# -------------------------
# 5) Detalhes do evento (card) com botão de mapa
# -------------------------
async def mostrar_detalhes_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("📋 Carregando detalhes...")

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _safe_edit(query, "Evento não encontrado ou não está mais ativo.")
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
        "🐐 *Nova sessão disponível para visitas!*\n\n"
        f"🏛 *LOJA {nome}{numero_fmt}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📍 Oriente: {oriente}\n"
        f"⚜️ Potência: {potencia}\n"
        f"📅 Data: {data_formatada}\n"
        f"🕕 Horário: {hora}\n"
        f"🕯 Tipo de sessão: {tipo_sessao}\n"
        f"📜 Rito: {rito}\n"
        f"🔺 Grau mínimo: {grau}\n"
        f"🎩 Traje: {traje}\n"
        f"🍽 Ágape: {agape}\n\n"
    )

    # Adiciona endereço e, se for link, prepara botão
    botoes_extras = []
    if endereco_raw:
        if endereco_raw.startswith(("http://", "https://")):
            # É um link - mostra como texto e adiciona botão
            texto += f"📍 *Link do local:* [Clique aqui]({endereco_raw})\n"
            botoes_extras.append([InlineKeyboardButton("📍 Abrir no mapa", url=endereco_raw)])
        else:
            # É texto normal
            texto += f"📍 *Endereço:* {endereco_raw}\n"
    else:
        texto += "📍 *Endereço:* Não informado\n"

    if obs:
        texto += f"\n📌 *Observações:* {obs}\n"

    user_id = update.effective_user.id
    ja_confirmou = buscar_confirmacao(id_evento, user_id)

    tipo_agape = extrair_tipo_agape(agape)
    botoes = []

    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    else:
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{_encode_cb(id_evento)}|gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{_encode_cb(id_evento)}|sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{_encode_cb(id_evento)}|pago")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{_encode_cb(id_evento)}|sem")])
        else:
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{_encode_cb(id_evento)}|sem")])

    botoes.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")])
    
    # Adiciona botões de mapa se houver
    if botoes_extras:
        botoes.extend(botoes_extras)
    
    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])

    await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))


# -------------------------
# 6) Confirmar presença (CORRIGIDO COM LOGS)
# -------------------------
async def iniciar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    partes = query.data.split("|")
    if len(partes) < 3:
        await _safe_edit(query, "Comando inválido.")
        return ConversationHandler.END

    _, id_evento_cod, tipo_agape = partes
    id_evento = _decode_cb(id_evento_cod)
    user_id = update.effective_user.id

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await _safe_edit(query, "Evento não encontrado ou não está mais ativo.")
        return ConversationHandler.END

    membro = buscar_membro(user_id)
    if not membro:
        # Guarda intenção de confirmar após cadastro
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "id_evento": id_evento,
            "tipo_agape": tipo_agape
        }
        botoes_cadastro = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Fazer cadastro", callback_data="iniciar_cadastro")]])
        await _safe_edit(
            query,
            "Olá! Antes de confirmar sua presença, preciso fazer seu cadastro.\n\nClique no botão abaixo para começar:",
            reply_markup=botoes_cadastro,
        )
        return ConversationHandler.END

    ja_confirmou = buscar_confirmacao(id_evento, user_id)
    if ja_confirmou:
        botoes = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
                [InlineKeyboardButton("🔙 Voltar", callback_data=f"evento|{_encode_cb(id_evento)}")],
            ]
        )
        await _safe_edit(query, "Você já confirmou presença para este evento.", reply_markup=botoes)
        return ConversationHandler.END

    participacao_agape = "Confirmada" if tipo_agape != "sem" else "Não selecionada"
    if tipo_agape == "gratuito":
        desc_agape = "Gratuito"
    elif tipo_agape == "pago":
        desc_agape = "Pago"
    else:
        desc_agape = "Não aplicável"

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
        "agape": f"{participacao_agape} ({desc_agape})" if participacao_agape == "Confirmada" else "Não",
        "veneravel_mestre": membro.get("Venerável Mestre", ""),
    }
    registrar_confirmacao(dados_confirmacao)

    # Notifica o secretário (se ele tiver ativo)
    await notificar_secretario(context, evento, membro, participacao_agape, desc_agape)

    data = str(evento.get("Data do evento", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    numero_loja = str(evento.get("Número da loja", "") or "").strip()
    horario = str(evento.get("Hora", "") or "").strip()
    potencia_evento = str(evento.get("Potência", "") or "").strip()

    data_obj = parse_data_evento(evento.get("Data do evento", ""))
    if data_obj:
        dia_semana = traduzir_dia(data_obj.strftime("%A"))
    else:
        dia_semana = str(evento.get("Dia da semana", "") or "").strip()

    numero_fmt = f" {numero_loja}" if numero_loja else ""

    resposta = (
        f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
        "*Resumo da confirmação:*\n"
        f"📅 {data} — {nome_loja}{numero_fmt}\n"
        f"⚜️ Potência: {potencia_evento}\n"
        f"📆 Dia: {dia_semana}\n"
        f"🕕 Horário: {horario}\n"
        f"🍽 Participação no ágape: {participacao_agape} ({desc_agape})\n\n"
        "Sua confirmação é muito importante! Ela nos ajuda a organizar tudo com carinho e evitar desperdícios.\n\n"
        "Fraterno abraço!"
    )

    botoes_privado = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("👥 Ver eventos", callback_data="ver_eventos")],
        ]
    )

    # LOGS PARA DIAGNÓSTICO
    logger.info(f"Tentando enviar mensagem de confirmação para user_id: {user_id}")
    logger.info(f"Conteúdo da mensagem: {resposta[:100]}...")

    try:
        # Verifica se o usuário tem chat com o bot
        try:
            await context.bot.get_chat(user_id)
            logger.info(f"Chat com {user_id} existe")
        except Exception as e:
            logger.error(f"Usuário {user_id} não tem chat com o bot: {e}")
            await query.answer("Você precisa iniciar conversa comigo no privado primeiro!")
            return ConversationHandler.END

        await context.bot.send_message(
            chat_id=user_id,
            text=resposta,
            parse_mode="Markdown",
            reply_markup=botoes_privado,
        )
        logger.info(f"Mensagem de confirmação enviada com sucesso para {user_id}")
    except Exception as e:
        logger.error(f"ERRO ao enviar mensagem de confirmação para {user_id}: {e}", exc_info=True)
        # Tenta enviar sem Markdown como fallback
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=resposta.replace("*", "").replace("_", ""),  # Remove markdown
                reply_markup=botoes_privado,
            )
            logger.info(f"Mensagem de confirmação enviada (sem markdown) para {user_id}")
        except Exception as e2:
            logger.error(f"ERRO FATAL ao enviar mensagem para {user_id}: {e2}")
            await query.answer("Erro ao enviar mensagem no privado. Verifique se você me bloqueou!")
            return ConversationHandler.END

    if update.effective_chat.type in ["group", "supergroup"]:
        await query.answer("Presença confirmada! Verifique seu privado.")
    else:
        await _safe_edit(query, "✅ Presença confirmada! Verifique a mensagem acima.")

    return ConversationHandler.END


# Função auxiliar para continuar confirmação após cadastro
async def iniciar_confirmacao_presenca_pos_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE, pos: dict):
    """Continua o fluxo de confirmação após o cadastro ser concluído."""
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
            text="Evento não encontrado. Tente confirmar novamente."
        )
        return

    membro = buscar_membro(user_id)
    if not membro:
        return

    # Verifica se já confirmou
    if buscar_confirmacao(id_evento, user_id):
        await context.bot.send_message(
            chat_id=user_id,
            text="Você já estava confirmado para este evento."
        )
        return

    participacao_agape = "Confirmada" if tipo_agape != "sem" else "Não selecionada"
    if tipo_agape == "gratuito":
        desc_agape = "Gratuito"
    elif tipo_agape == "pago":
        desc_agape = "Pago"
    else:
        desc_agape = "Não aplicável"

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
        "agape": f"{participacao_agape} ({desc_agape})" if participacao_agape == "Confirmada" else "Não",
        "veneravel_mestre": membro.get("Venerável Mestre", ""),
    }
    registrar_confirmacao(dados_confirmacao)

    # Notifica o secretário
    await notificar_secretario(context, evento, membro, participacao_agape, desc_agape)

    data = str(evento.get("Data do evento", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    numero_loja = str(evento.get("Número da loja", "") or "").strip()
    horario = str(evento.get("Hora", "") or "").strip()

    numero_fmt = f" {numero_loja}" if numero_loja else ""

    resposta = (
        f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
        "*Resumo da confirmação:*\n"
        f"📅 {data} — {nome_loja}{numero_fmt}\n"
        f"🕕 Horário: {horario}\n"
        f"🍽 Participação no ágape: {participacao_agape} ({desc_agape})\n\n"
        "Fraterno abraço!"
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=resposta,
        parse_mode="Markdown",
    )


# -------------------------
# 7) Cancelar presença
# -------------------------
async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    # Confirmação (passo 2)
    if query.data.startswith("confirma_cancelar|"):
        _, id_evento_cod = query.data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        cancelou = cancelar_confirmacao(id_evento, user_id)
        if cancelou:
            await _safe_edit(
                query,
                "❌ Presença cancelada.\n\n"
                f"Se mudar de ideia, basta confirmar novamente.",
            )
        else:
            await _safe_edit(query, "Não foi possível cancelar. Você não estava confirmado para este evento.")
        return

    # Pedido (passo 1)
    if query.data.startswith("cancelar|"):
        _, id_evento_cod = query.data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        if update.effective_chat.type in ["group", "supergroup"]:
            teclado = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar|{_encode_cb(id_evento)}")],
                    [InlineKeyboardButton("🔙 Não, voltar", callback_data=f"evento|{_encode_cb(id_evento)}")],
                ]
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Confirmar cancelamento da sua presença?",
                reply_markup=teclado,
            )
            await _safe_edit(query, "Instruções enviadas no privado.")
            return

        cancelou = cancelar_confirmacao(id_evento, user_id)
        if cancelou:
            await _safe_edit(
                query,
                "❌ Presença cancelada.\n\n"
                f"Se mudar de ideia, basta confirmar novamente.",
            )
        else:
            await _safe_edit(query, "Não foi possível cancelar. Você não estava confirmado para este evento.")
        return

    await _safe_edit(query, "Comando de cancelamento inválido.")


# -------------------------
# 8) Ver confirmados (CORRIGIDO - VERSÃO ORIGINAL)
# -------------------------
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
        botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{_encode_cb(id_evento)}|sem")])

    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])

    # COMPORTAMENTO ORIGINAL: SEMPRE envia nova mensagem
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


# -------------------------
# 9) Minhas confirmações (com separação futuro/histórico)
# -------------------------
async def minhas_confirmacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu principal de confirmações do membro (escolher entre futuro ou histórico)."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Próximos eventos", callback_data="minhas_confirmacoes_futuro")],
        [InlineKeyboardButton("📜 Histórico", callback_data="minhas_confirmacoes_historico")],
        [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
    ])

    await _safe_edit(
        query,
        "📌 *Suas confirmações*\n\n"
        "Escolha o que deseja ver:",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


async def minhas_confirmacoes_futuro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista eventos futuros que o membro confirmou."""
    query = update.callback_query
    if not query:
        return
    await query.answer("📅 Buscando eventos futuros...")

    user_id = update.effective_user.id
    eventos = listar_eventos() or []
    eventos = _eventos_ordenados(eventos)
    
    from datetime import datetime
    hoje = datetime.now().date()

    confirmados_futuro = []
    for ev in eventos:
        id_evento = normalizar_id_evento(ev)
        if buscar_confirmacao(id_evento, user_id):
            # Verifica se é futuro
            data_str = ev.get("Data do evento", "")
            try:
                data_evento = datetime.strptime(data_str, "%d/%m/%Y").date()
                if data_evento >= hoje:
                    confirmados_futuro.append(ev)
            except:
                # Se não conseguir parsear, considera como futuro (fallback seguro)
                confirmados_futuro.append(ev)

    if not confirmados_futuro:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Ver histórico", callback_data="minhas_confirmacoes_historico")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes")],
            [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
        ])
        await _safe_edit(
            query,
            "📅 *Próximos eventos*\n\n"
            "Você não possui confirmações em eventos futuros.",
            parse_mode="Markdown",
            reply_markup=teclado,
        )
        return

    botoes = []
    for ev in confirmados_futuro[:MAX_EVENTOS_LISTA]:
        id_evento = normalizar_id_evento(ev)
        label = _linha_botao_evento(ev)
        botoes.append([InlineKeyboardButton(label, callback_data=f"detalhes_confirmado|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("📜 Ver histórico", callback_data="minhas_confirmacoes_historico")])
    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes")])
    botoes.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])

    await _safe_edit(
        query,
        "📅 *Próximos eventos*\n\n"
        "Eventos futuros que você confirmou:\n"
        "Selecione para ver detalhes:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def minhas_confirmacoes_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista eventos passados que o membro confirmou."""
    query = update.callback_query
    if not query:
        return
    await query.answer("📜 Buscando histórico...")

    user_id = update.effective_user.id
    eventos = listar_eventos() or []
    eventos = _eventos_ordenados(eventos)
    
    from datetime import datetime
    hoje = datetime.now().date()

    confirmados_passado = []
    for ev in eventos:
        id_evento = normalizar_id_evento(ev)
        if buscar_confirmacao(id_evento, user_id):
            # Verifica se é passado
            data_str = ev.get("Data do evento", "")
            try:
                data_evento = datetime.strptime(data_str, "%d/%m/%Y").date()
                if data_evento < hoje:
                    confirmados_passado.append(ev)
            except:
                # Se não conseguir parsear, não inclui no histórico
                continue

    if not confirmados_passado:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Ver próximos", callback_data="minhas_confirmacoes_futuro")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes")],
            [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
        ])
        await _safe_edit(
            query,
            "📜 *Histórico*\n\n"
            "Você ainda não participou de nenhum evento.",
            parse_mode="Markdown",
            reply_markup=teclado,
        )
        return

    botoes = []
    for ev in confirmados_passado[:MAX_EVENTOS_LISTA]:
        id_evento = normalizar_id_evento(ev)
        label = _linha_botao_evento(ev)
        # No histórico, ao clicar mostra apenas os detalhes (sem opção de cancelar)
        botoes.append([InlineKeyboardButton(label, callback_data=f"detalhes_historico|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("📅 Ver próximos", callback_data="minhas_confirmacoes_futuro")])
    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes")])
    botoes.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])

    await _safe_edit(
        query,
        "📜 *Histórico*\n\n"
        "Eventos que você participou:\n"
        "Selecione para ver detalhes:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


# -------------------------
# 10) Detalhes do confirmado (para eventos futuros)
# -------------------------
async def detalhes_confirmado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra detalhes de uma confirmação futura (com botão cancelar)."""
    query = update.callback_query
    if not query:
        return
    await query.answer("📋 Carregando detalhes...")

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        teclado = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes_futuro")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]
        )
        await _safe_edit(query, "Evento não encontrado ou não está mais ativo.", reply_markup=teclado)
        return

    nome = str(evento.get("Nome da loja", "") or "").strip()
    numero = str(evento.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero else ""
    data_txt = str(evento.get("Data do evento", "") or "").strip()
    hora = str(evento.get("Hora", "") or "").strip()
    oriente = str(evento.get("Oriente", "") or "").strip()
    potencia = str(evento.get("Potência", "") or "").strip()

    # Busca a confirmação para ver detalhes do ágape
    user_id = update.effective_user.id
    confirmacao = buscar_confirmacao(id_evento, user_id)
    agape_info = ""
    if confirmacao:
        agape = confirmacao.get("Ágape", "")
        if agape:
            agape_info = f"\n🍽 *Ágape:* {agape}"

    texto = (
        "*Confirmação registrada*\n\n"
        f"🏛 {nome}{numero_fmt}\n"
        f"📅 {data_txt}\n"
        f"🕕 {hora}\n"
        f"📍 {oriente}\n"
        f"⚜️ {potencia}{agape_info}\n"
    )

    teclado = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes_futuro")],
            [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
        ]
    )

    await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=teclado)


# -------------------------
# 11) Detalhes do histórico (sem opção de cancelar)
# -------------------------
async def detalhes_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra detalhes de uma confirmação passada (sem botão cancelar)."""
    query = update.callback_query
    if not query:
        return
    await query.answer("📜 Carregando histórico...")

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        teclado = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes_historico")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]
        )
        await _safe_edit(query, "Evento não encontrado ou não está mais ativo.", reply_markup=teclado)
        return

    nome = str(evento.get("Nome da loja", "") or "").strip()
    numero = str(evento.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero else ""
    data_txt = str(evento.get("Data do evento", "") or "").strip()
    hora = str(evento.get("Hora", "") or "").strip()
    oriente = str(evento.get("Oriente", "") or "").strip()
    potencia = str(evento.get("Potência", "") or "").strip()

    # Busca a confirmação para ver detalhes do ágape
    user_id = update.effective_user.id
    confirmacao = buscar_confirmacao(id_evento, user_id)
    agape_info = ""
    if confirmacao:
        agape = confirmacao.get("Ágape", "")
        if agape:
            agape_info = f"\n🍽 *Ágape:* {agape}"

    texto = (
        "*📜 Participação em evento passado*\n\n"
        f"🏛 {nome}{numero_fmt}\n"
        f"📅 {data_txt}\n"
        f"🕕 {hora}\n"
        f"📍 {oriente}\n"
        f"⚜️ {potencia}{agape_info}\n\n"
        "_Este evento já aconteceu._"
    )

    teclado = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes_historico")],
            [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
        ]
    )

    await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=teclado)


# -------------------------
# 12) Fechar mensagem
# -------------------------
async def fechar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    try:
        await query.delete_message()
    except Exception:
        try:
            await _safe_edit(query, "Fechado.")
        except Exception:
            pass


# -------------------------
# ConversationHandler (mantido)
# -------------------------
confirmacao_presenca_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmacao_presenca, pattern=r"^confirmar\|")],
    states={},
    fallbacks=[CommandHandler("cancelar", cancelar_presenca)],
)