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

import asyncio
import logging
import urllib.parse
import calendar
import functools
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional, Tuple, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, CommandHandler

from src.sheets_supabase import (
    listar_eventos,
    buscar_membro,
    registrar_confirmação,
    cancelar_confirmação,
    buscar_confirmação,
    listar_confirmações_por_evento,
    atualizar_evento,
    get_notificacao_status,
    listar_notificacoes_secretario_pendentes,
    listar_secretarios_com_notificacoes_pendentes,
    registrar_notificacao_secretario_pendente,
    remover_notificacoes_secretario_pendentes,
    obter_secretario_responsavel_evento,
)
from src.ajuda.dicas import enviar_dica_contextual
from src.messages import (
    EVENTO_NAO_ENCONTRADO,
    JA_CONFIRMOU,
    NAO_CONFIRMOU,
    NOTIFICACAO_NOVA_CONFIRMACAO,
    PRESENCA_CANCELADA,
    MENSAGEM_CONFIRMACAO_AGAPE,
    CONFIRMACAO_SEM_CADASTRO,
    CONFIRMACAO_FALLBACK_GRUPO_CADASTRO,
    CONFIRMACAO_CALLBACK_ABRIR_PRIVADO_CADASTRO,
    CONFIRMACAO_SESSAO_NAO_ENCONTRADA,
    CONFIRMACAO_JA_CONFIRMADO_POS_CADASTRO,
    CONFIRMACAO_SECRETARIO_TMPL,
    CONFIRMACAO_COM_AGAPE_TMPL,
    CONFIRMACAO_SEM_AGAPE_TMPL,
    CANCELAR_PRESENCA_SUCESSO_GRUPO,
    CANCELAR_PRESENCA_CONFIRMAR,
    CANCELAR_PRESENCA_FALLBACK_GRUPO,
    CANCELAR_PRESENCA_CALLBACK_ABRIR_PRIVADO,
    CANCELAR_PRESENCA_CALLBACK_INSTRUCOES,
)

from src.bot import (
    navegar_para,
    voltar_ao_menu_principal,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)

# Fallback em memória para instalações que ainda não possuem a coluna
# `grupo_mensagem_id` em `eventos`.
_CACHE_POST_EVENTO_GRUPO: Dict[str, Tuple[int, int]] = {}


_HORA_SILENCIO_INICIO = 22
_HORA_SILENCIO_FIM = 7


def _link_privado_bot(context: ContextTypes.DEFAULT_TYPE, start_param: str = "start") -> str:
    """Monta link para abrir o chat privado do bot."""
    username = (getattr(context.bot, "username", None) or "BodeAndarilhoBot").lstrip("@")
    if start_param:
        return f"https://t.me/{username}?start={start_param}"
    return f"https://t.me/{username}"


async def _responder_callback_seguro(query, texto: Optional[str] = None, show_alert: bool = False):
    """Responde callback sem interromper o fluxo quando a query já expirou."""
    if not query:
        return
    try:
        if texto is None:
            await query.answer()
        else:
            await query.answer(texto, show_alert=show_alert)
    except BadRequest as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.debug("Callback expirado ignorado: %s", e)
            return
        logger.warning("Falha ao responder callback: %s", e)


def _em_horario_silencioso_secretario(dt: Optional[datetime] = None) -> bool:
    agora = dt or datetime.now()
    hora = agora.hour
    return hora >= _HORA_SILENCIO_INICIO or hora < _HORA_SILENCIO_FIM


def _texto_resumo_notificacoes_pendentes(itens: List[Dict[str, str]]) -> str:
    total = len(itens)
    linhas = []
    for i, item in enumerate(itens[:20], start=1):
        agape = item.get("agape") or item.get("ágape", "")
        linhas.append(
            f"{i}. {item.get('nome', 'Irmão')} | {item.get('data', '')} - {item.get('loja', '')} | {agape}"
        )

    if total > 20:
        linhas.append(f"... e mais {total - 20} confirmação(ões).")

    corpo = "\n".join(linhas) if linhas else "Sem detalhes disponíveis."
    return (
        "📨 *Resumo de confirmações no período de silêncio*\n\n"
        f"Total acumulado: *{total}*\n"
        "Período: 22:00 às 07:00\n\n"
        f"{corpo}"
    )


async def _flush_notificacoes_secretario_ids(bot, secretario_ids: List[int]) -> None:
    if not secretario_ids:
        return

    for sid in secretario_ids:
        itens = await asyncio.to_thread(listar_notificacoes_secretario_pendentes, sid)
        if not itens:
            continue
        try:
            await bot.send_message(
                chat_id=sid,
                text=_texto_resumo_notificacoes_pendentes(itens),
                parse_mode="Markdown",
            )
            await asyncio.to_thread(remover_notificacoes_secretario_pendentes, sid)
            logger.info("Resumo de confirmações pendentes enviado ao secretário %s (%s itens)", sid, len(itens))
        except Exception as e:
            logger.error("Erro ao enviar resumo pendente ao secretário %s: %s", sid, e)


async def flush_notificacoes_secretario_adiadas(bot) -> None:
    """Envia resumos únicos das confirmações acumuladas no período de silêncio."""
    secretario_ids = await asyncio.to_thread(listar_secretarios_com_notificacoes_pendentes)
    await _flush_notificacoes_secretario_ids(bot, secretario_ids)


async def _auto_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 15):
    """Autoapaga mensagem enviada no grupo, sem impactar o fluxo principal."""
    await asyncio.sleep(max(1, int(delay)))
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("Não foi possivel autoapagar mensagem %s no chat %s: %s", message_id, chat_id, e)


def registrar_post_evento_grupo(id_evento: str, chat_id: int, message_id: int) -> None:
    """Registra em memória o post do evento no grupo (fallback sem coluna persistida)."""
    if not id_evento:
        return
    _CACHE_POST_EVENTO_GRUPO[id_evento] = (int(chat_id), int(message_id))

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

MAX_EVENTOS_LISTA = 40
MESES_PROXIMOS_QTD = 6

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


def extrair_tipo_ágape(texto_ágape: str) -> str:
    texto = (texto_ágape or "").lower()
    if "pago" in texto or "dividido" in texto:
        return "pago"
    if "gratuito" in texto:
        return "gratuito"
    if "com ágape" in texto or "com ágape" in texto:
        return "com"
    if texto.strip() in ("sim", "s"):
        return "com"
    return "sem"


def _teclado_confirmação_evento(id_evento: str, ágape_evento: str) -> List[List[InlineKeyboardButton]]:
    """Monta botoes de confirmação conforme tipo de ágape da sessão."""
    id_cod = _encode_cb(id_evento)
    tipo_ágape = extrair_tipo_ágape(ágape_evento)

    if tipo_ágape == "gratuito":
        return [
            [InlineKeyboardButton("\U0001F37D Confirmar com ágape (gratuito)", callback_data=f"confirmar|{id_cod}|gratuito")],
            [InlineKeyboardButton("\u2705 Confirmar sem ágape", callback_data=f"confirmar|{id_cod}|sem")],
        ]

    if tipo_ágape == "pago":
        return [
            [InlineKeyboardButton("\U0001F37D Confirmar com ágape (pago)", callback_data=f"confirmar|{id_cod}|pago")],
            [InlineKeyboardButton("\u2705 Confirmar sem ágape", callback_data=f"confirmar|{id_cod}|sem")],
        ]

    if tipo_ágape == "com":
        return [
            [InlineKeyboardButton("\U0001F37D Confirmar com ágape", callback_data=f"confirmar|{id_cod}|com")],
            [InlineKeyboardButton("\u2705 Confirmar sem ágape", callback_data=f"confirmar|{id_cod}|sem")],
        ]

    return [[InlineKeyboardButton("\u2705 Confirmar presença", callback_data=f"confirmar|{id_cod}|sem")]]


def _escape_md(value: Any) -> str:
    """Escapa caracteres especiais de Markdown usado nas mensagens do grupo."""
    s = "" if value is None else str(value)
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def _normalizar_url_local(value: Any) -> str:
    """Retorna URL do local quando válida para abrir no Telegram."""
    raw = "" if value is None else str(value).strip()
    if raw.startswith(("http://", "https://")):
        return raw
    return ""


def montar_texto_publicacao_evento(evento: dict) -> str:
    """Monta o texto principal do card de evento publicado no grupo."""
    aviso = str(evento.get("_aviso_resumo") or "").strip()
    nome = _escape_md(evento.get("Nome da loja", ""))
    número = _escape_md(evento.get("Número da loja", ""))
    número_fmt = f" {número}" if número and número != "0" else ""
    data_txt = _escape_md(evento.get("Data do evento", ""))
    hora_txt = _escape_md(evento.get("Hora", ""))
    dia_semana_raw = str(evento.get("Dia da semana", "") or "").strip()
    dia_semana_fmt = ""
    if dia_semana_raw:
        dia_traduzido = traduzir_dia_abreviado(dia_semana_raw)
        dia_semana_fmt = _escape_md(dia_traduzido.split("-")[0].strip().lower())
    oriente = _escape_md(evento.get("Oriente", ""))
    potencia = _escape_md(evento.get("Potência", ""))
    grau = _escape_md(evento.get("Grau", ""))
    tipo = _escape_md(evento.get("Tipo de sessão", ""))
    rito = _escape_md(evento.get("Rito", ""))
    traje = _escape_md(evento.get("Traje obrigatório", ""))
    ágape = _escape_md(evento.get("Ágape", ""))
    endereço_raw = "" if evento.get("Endereço da sessão") is None else str(evento.get("Endereço da sessão")).strip()
    endereço = _escape_md(endereço_raw)
    url_local = _normalizar_url_local(endereço_raw)
    observacao = _escape_md(evento.get("Observações", "")) or "-"
    status = str(evento.get("Status", "") or "").strip().lower()

    cabecalho = "NOVA SESSÃO"
    if aviso:
        cabecalho = f"ALTERAÇÃO: {_escape_md(aviso)}\n\n" + cabecalho

    data_hora = f"{data_txt} ({dia_semana_fmt}) • {hora_txt}" if dia_semana_fmt else f"{data_txt} • {hora_txt}"

    texto = (
        f"{cabecalho}\n\n"
        f"{data_hora}\n"
        f"Grau: {grau}\n\n"
        "LOJA\n"
        f"{nome}{número_fmt}\n"
        f"{oriente} - {potencia}\n\n"
        "SESSÃO\n"
        f"Tipo: {tipo}\n"
        f"Rito: {rito}\n"
        f"Traje: {traje}\n"
        f"Ágape: {ágape}\n\n"
        "ORDEM DO DIA / OBSERVAÇÕES\n"
        f"{observacao}\n\n"
    )

    if url_local:
        texto += f"Local: [Abrir no mapa]({url_local})"
    else:
        texto += f"Local: {endereço}"

    if status == "cancelado":
        texto += "\n\n⛔ *STATUS:* CANCELADO"
    return texto


def montar_teclado_publicacao_evento(evento: dict) -> Optional[InlineKeyboardMarkup]:
    """Monta teclado do card publicado no grupo conforme status atual."""
    status_interacao = _status_interacao_evento(evento)
    if status_interacao != "disponivel":
        return None

    id_evento = normalizar_id_evento(evento)
    ágape = str(evento.get("Ágape", "") or "")
    endereço_raw = "" if evento.get("Endereço da sessão") is None else str(evento.get("Endereço da sessão")).strip()
    url_local = _normalizar_url_local(endereço_raw)
    linhas = _teclado_confirmação_evento(id_evento, ágape)
    linhas.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")])
    if url_local:
        linhas.append([InlineKeyboardButton("📍 Abrir no mapa", url=url_local)])
    return InlineKeyboardMarkup(linhas)


async def sincronizar_resumo_evento_grupo(context: ContextTypes.DEFAULT_TYPE, evento: dict) -> bool:
    """Atualiza o card original do evento no grupo após edição de dados/status."""
    id_evento = normalizar_id_evento(evento)
    grupo_id = _tid_to_int(evento.get("Telegram ID do grupo") or evento.get("grupo_telegram_id"))
    msg_id = _tid_to_int(evento.get("Telegram Message ID do grupo") or evento.get("grupo_mensagem_id"))

    async def _publicar_novo_card() -> bool:
        """Fallback para eventos legados sem message_id: publica novo card e persiste ID."""
        if not grupo_id:
            logger.warning("Não foi possível sincronizar card do evento %s: grupo_id ausente.", id_evento)
            return False
        try:
            nova_msg = await context.bot.send_message(
                chat_id=grupo_id,
                text=montar_texto_publicacao_evento(evento),
                parse_mode="Markdown",
                reply_markup=montar_teclado_publicacao_evento(evento),
            )
            registrar_post_evento_grupo(id_evento, grupo_id, nova_msg.message_id)

            # Persiste para futuras sincronizações após restart.
            atualizado = atualizar_evento(0, {
                "ID Evento": id_evento,
                "Telegram Message ID do grupo": str(nova_msg.message_id),
            })
            if not atualizado:
                logger.warning(
                    "Card novo do evento %s foi publicado, mas não foi possível persistir message_id.",
                    id_evento,
                )
            return True
        except Exception as e:
            logger.warning("Falha ao publicar card fallback do evento %s no grupo: %s", id_evento, e)
            return False

    # Fallback para ambientes sem persistência do message_id no banco.
    if (not grupo_id or not msg_id) and id_evento in _CACHE_POST_EVENTO_GRUPO:
        grupo_id, msg_id = _CACHE_POST_EVENTO_GRUPO[id_evento]

    if not grupo_id or not msg_id:
        return await _publicar_novo_card()

    try:
        await context.bot.edit_message_text(
            chat_id=grupo_id,
            message_id=msg_id,
            text=montar_texto_publicacao_evento(evento),
            parse_mode="Markdown",
            reply_markup=montar_teclado_publicacao_evento(evento),
        )
        return True
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return True
        # Se o post original não existe mais, publica um novo e reancora o evento.
        if "message to edit not found" in str(e).lower():
            return await _publicar_novo_card()
        logger.warning("Falha ao sincronizar card do evento no grupo (id_evento=%s): %s", id_evento, e)
        return False
    except Exception as e:
        logger.warning("Erro ao sincronizar card do evento no grupo (id_evento=%s): %s", id_evento, e)
        return False


def _texto_participacao_ágape(tipo_ágape: str) -> str:
    """Retorna texto humano para a escolha de participação no ágape."""
    if tipo_ágape == "gratuito":
        return "Participação com ágape (gratuito) foi selecionada."
    if tipo_ágape == "pago":
        return "Participação com ágape (pago) foi selecionada."
    if tipo_ágape == "com":
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


def _data_hora_evento(ev: dict) -> Optional[datetime]:
    data_dt = parse_data_evento(ev.get("Data do evento", ""))
    if not data_dt:
        return None

    hh, mm = _parse_hora(ev.get("Hora", ""))
    if hh == 99:
        hh, mm = 23, 59

    try:
        return data_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except ValueError:
        return data_dt


def _status_interacao_evento(ev: dict, agora: Optional[datetime] = None) -> str:
    status = str(ev.get("Status", "") or "").strip().lower()
    if status == "cancelado":
        return "cancelado"

    data_hora = _data_hora_evento(ev)
    if data_hora and data_hora < (agora or datetime.now()):
        return "ocorrido"

    return "disponivel"


def _mensagem_status_evento(ev: dict) -> str:
    status_interacao = _status_interacao_evento(ev)
    if status_interacao == "cancelado":
        return "⛔ *Status:* sessão cancelada."
    if status_interacao == "ocorrido":
        return "ℹ️ *Status:* esta sessão já ocorreu."
    return ""


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
    número = (dados_membro_ou_snapshot.get("Número da loja") or dados_membro_ou_snapshot.get("número_loja") or "")
    número = str(número).strip()

    oriente = (dados_membro_ou_snapshot.get("Oriente") or dados_membro_ou_snapshot.get("oriente") or "").strip()
    potencia = (dados_membro_ou_snapshot.get("Potência") or dados_membro_ou_snapshot.get("potencia") or "").strip()

    loja_composta = f"{loja} {número}".strip()
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


def _filtrar_por_período(eventos: List[dict], token: str) -> Tuple[str, List[dict]]:
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
    número = str(ev.get("N\u00famero da loja", "") or "").strip()
    hora = str(ev.get("Hora", "") or "").strip()

    número_fmt = f" {número}" if número else ""
    hora_fmt = hora if hora else "--"
    data_curta = _formatar_data_curta(ev)

    return f"\U0001F4C5 {data_curta} | \U0001F550 {hora_fmt} | \U0001F3DB {nome}{número_fmt}"


def contar_confirmações_futuras(user_id: int) -> int:
    """Conta quantas sessões futuras o membro ja confirmou."""
    eventos = _eventos_ordenados(listar_eventos() or [])
    agora = datetime.now()
    total = 0

    for ev in eventos:
        if _status_interacao_evento(ev, agora) != "disponivel":
            continue
        id_evento = normalizar_id_evento(ev)
        if buscar_confirmação(id_evento, user_id):
            total += 1

    return total


# ============================================
# FUNÇÃO PARA NOTIFICAR SECRETÁRIO
# ============================================

async def notificar_secretario(context: ContextTypes.DEFAULT_TYPE, evento: dict, membro: dict, tipo_ágape: str):
    """
    Notifica o secretário que criou o evento sobre uma nova confirmação de presença.

    O secretário é resolvido prioritariamente pelo vínculo da loja; fallback legado
    considera os campos antigos do evento.
    """
    secretario_id = obter_secretario_responsavel_evento(evento)
    if not secretario_id:
        logger.debug(f"Nenhum secretário definido para o evento")
        return

    # Verifica se o SECRETÁRIO quer receber notificações
    if not get_notificacao_status(secretario_id):
        logger.debug(f"Secretário {secretario_id} desativou notificações")
        return

    nome_loja = evento.get("Nome da loja", "")
    número = evento.get("Número da loja", "")
    número_fmt = f" {número}" if número else ""
    data = evento.get("Data do evento", "")
    nome_membro = membro.get("Nome", "")
    texto_participacao = _texto_participacao_ágape(tipo_ágape)

    texto = NOTIFICACAO_NOVA_CONFIRMACAO.format(
        nome=nome_membro,
        data=data,
        loja=f"{nome_loja}{número_fmt}",
        ágape=texto_participacao,
    )

    item_pendente = {
        "nome": nome_membro,
        "data": str(data or ""),
        "loja": f"{nome_loja}{número_fmt}",
        "agape": texto_participacao,
    }

    if _em_horario_silencioso_secretario():
        ok = await asyncio.to_thread(registrar_notificacao_secretario_pendente, secretario_id, item_pendente)
        if ok:
            logger.info("Notificação do secretário %s persistida por horário de silêncio.", secretario_id)
        else:
            logger.warning("Falha ao persistir notificação pendente do secretário %s.", secretario_id)
        return

    # Ao sair da janela de silêncio, dispara primeiro um resumo consolidado, se existir.
    await _flush_notificacoes_secretario_ids(context.bot, [secretario_id])

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
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARCO", 4: "ABRIL",
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
    linhas.append(f"\U0001F4C5 *{meses_pt[mes]} {ano}*")
    linhas.append("```")
    linhas.append(" DOM SEG TER QUA QUI SEX SAB")

    for semana in cal:
        linha = ""
        for dia in semana:
            if dia == 0:
                linha += "    "
            else:
                if dia in dias_com_evento:
                    linha += f" {dia:2d}o"
                else:
                    linha += f" {dia:2d} "
        linhas.append(linha)

    linhas.append("```")
    linhas.append("")
    linhas.append("Legenda: o Dias com sessão")
    linhas.append(f"Total de sessões no mes: {len(dias_com_evento)}")

    return "\n".join(linhas)


# ============================================
# HANDLERS PRINCIPAIS
# ============================================

async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001F4C5 Calendário do mes", callback_data="calendario|0|0")],
        [InlineKeyboardButton("\U0001F4CD Esta semana", callback_data=f"data|{TOKEN_SEMANA_ATUAL}")],
        [InlineKeyboardButton("\U0001F4CD Próxima semana", callback_data=f"data|{TOKEN_PROXIMA_SEMANA}")],
        [InlineKeyboardButton("\U0001F5D3 Este mes", callback_data=f"data|{TOKEN_MES_ATUAL}")],
        [InlineKeyboardButton("\U0001F5D3 Próximos meses", callback_data=f"data|{TOKEN_PROXIMOS_MESES}")],
        [InlineKeyboardButton("\U0001F53A Filtrar por grau", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")],
        [InlineKeyboardButton("\U0001F519 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Ver Sessões",
        "\U0001F4C5 *Sessões Agendadas*\n\nEscolha como deseja buscar as sessões:",
        teclado
    )


async def mostrar_calendario(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            except Exception:
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
            InlineKeyboardButton("Anterior", callback_data=f"calendario|{ano_ant}|{mes_ant}"),
            InlineKeyboardButton("Mes atual", callback_data="calendario_atual"),
            InlineKeyboardButton("Proximo", callback_data=f"calendario|{ano_prox}|{mes_prox}"),
        ],
        [InlineKeyboardButton("\U0001F4CB Ver sessões do mes", callback_data=f"data|{TOKEN_MES_ATUAL}")],
        [InlineKeyboardButton("\U0001F519 Voltar", callback_data="ver_eventos")],
    ]

    await navegar_para(
        update, context,
        "Ver Sessões > Calendário",
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
            [InlineKeyboardButton(f"\U0001F53A {GRAU_APRENDIZ}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_APRENDIZ}")],
            [InlineKeyboardButton(f"\U0001F53A {GRAU_COMPANHEIRO}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_COMPANHEIRO}")],
            [InlineKeyboardButton(f"\U0001F53A {GRAU_MESTRE}", callback_data=f"grau|{TOKEN_POR_GRAU_MENU}|{GRAU_MESTRE}")],
            [InlineKeyboardButton("\U0001F519 Voltar", callback_data="ver_eventos")],
        ])
        await navegar_para(
            update, context,
            "Ver Sessões > Filtrar por Grau",
            "\U0001F53A *Selecione o grau desejado:*",
            teclado
        )
        return

    eventos = listar_eventos() or []

    if token_or_data in (TOKEN_SEMANA_ATUAL, TOKEN_PROXIMA_SEMANA, TOKEN_MES_ATUAL, TOKEN_PROXIMOS_MESES):
        titulo, filtrados = _filtrar_por_período(eventos, token_or_data)

        if not filtrados:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                f"*{titulo}*\n\nNenhuma sessão encontrada neste filtro.\n\nVocê pode tentar outro período ou consultar o calendario do mes.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4C5 Calendário do mes", callback_data="calendario|0|0")],
                    [InlineKeyboardButton("\U0001F5D3 Ver outro período", callback_data="ver_eventos")],
                    [InlineKeyboardButton("\U0001F519 Voltar ao menu", callback_data="menu_principal")],
                ])
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

        botoes.append([InlineKeyboardButton("\U0001F519 Voltar", callback_data="ver_eventos")])

        await navegar_para(
            update, context,
            f"Ver Sessões > {titulo}",
            f"\U0001F4C5 *Sessões encontradas*\n\n{titulo}\n\nSelecione uma sessão para ver os detalhes:",
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
                f"*{titulo}*\n\nNenhuma sessão encontrada neste filtro.\n\nVocê pode escolher outro grau ou voltar para os demais períodos.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F53A Escolher outro grau", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")],
                    [InlineKeyboardButton("\U0001F519 Voltar", callback_data="ver_eventos")],
                ])
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

        botoes.append([InlineKeyboardButton("\U0001F519 Voltar", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")])

        await navegar_para(
            update, context,
            f"Ver Sessões > Filtrar por Grau > {grau}",
            f"\U0001F4C5 *Sessões encontradas*\n\n{titulo}\n\nSelecione uma sessão para ver os detalhes:",
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
            "Sessao não encontrada ou não esta mais ativa.",
            limpar_conteudo=True
        )
        return

    nome = str(evento.get("Nome da loja", "") or "").strip()
    número = str(evento.get("Número da loja", evento.get("N\u00famero da loja", "")) or "").strip()
    número_fmt = f" {número}" if número else ""
    oriente = str(evento.get("Oriente", "") or "").strip()
    potencia = str(evento.get("Potência", evento.get("Pot\u00eancia", "")) or "").strip()
    data = evento.get("Data do evento", "")
    hora = str(evento.get("Hora", "") or "").strip()
    tipo_sessão = str(evento.get("Tipo de sessão", evento.get("Tipo de sess\u00e3o", "")) or "").strip()
    rito = str(evento.get("Rito", "") or "").strip()
    grau = normalizar_grau_nome(str(evento.get("Grau", "") or "").strip())
    traje = str(evento.get("Traje obrigatorio", evento.get("Traje obrigat\u00f3rio", "")) or "").strip()
    ágape = str(evento.get("Ágape", evento.get("\u00c1gape", "")) or "").strip()
    obs = str(evento.get("Observações", evento.get("Observa\u00e7\u00f5es", "")) or "").strip()
    endereço_raw = str(evento.get("Endereço da sessão", evento.get("Endere\u00e7o da sess\u00e3o", "")) or "").strip()

    data_obj = parse_data_evento(data)
    if data_obj:
        dia_semana = traduzir_dia(data_obj.strftime("%A"))
        data_formatada = f"{data_obj.strftime('%d/%m/%Y')} ({dia_semana})"
    else:
        data_formatada = str(data or "").strip()

    texto = (
        "\U0001F4DC *Detalhes da Sessao*\n\n"
        f"*Loja:* {nome}{número_fmt}\n"
        f"*Oriente:* {oriente}\n"
        f"*Potência:* {potencia}\n"
        f"*Data:* {data_formatada}\n"
        f"*Horário:* {hora}\n"
        f"*Tipo:* {tipo_sessão}\n"
        f"*Rito:* {rito}\n"
        f"*Grau mínimo:* {grau}\n"
        f"*Traje:* {traje}\n"
        f"*Ágape:* {ágape}\n"
    )

    botoes_extras = []
    if endereço_raw:
        if endereço_raw.startswith(("http://", "https://")):
            texto += f"\n*Local:* [Abrir mapa]({endereço_raw})"
            botoes_extras.append([InlineKeyboardButton("\U0001F4CD Abrir no mapa", url=endereço_raw)])
        else:
            texto += f"\n*Endereço:* {endereço_raw}"
    else:
        texto += "\n*Endereço:* Não informado"

    if obs:
        texto += f"\n\n*Observações:* {obs}"

    user_id = update.effective_user.id
    ja_confirmou = buscar_confirmação(id_evento, user_id)
    status_msg = _mensagem_status_evento(evento)
    botoes = []

    if status_msg:
        texto += f"\n\n{status_msg}"
    elif ja_confirmou:
        botoes.append([InlineKeyboardButton("\u274C Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    else:
        botoes.extend(_teclado_confirmação_evento(id_evento, ágape))

    botoes.append([InlineKeyboardButton("\U0001F465 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")])

    if botoes_extras:
        botoes.extend(botoes_extras)

    botoes.append([InlineKeyboardButton("\U0001F519 Voltar", callback_data="ver_eventos")])

    await navegar_para(
        update, context,
        f"Ver Sessões > {nome}",
        texto,
        InlineKeyboardMarkup(botoes)
    )



# ============================================
# CONFIRMAÇÃO DE PRESENÇA
# ============================================

async def iniciar_confirmação_presença(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partes = query.data.split("|")
    if len(partes) < 3:
        return ConversationHandler.END

    _, id_evento_cod, tipo_ágape = partes
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
            EVENTO_NAO_ENCONTRADO,
            limpar_conteudo=True
        )
        return ConversationHandler.END

    status_interacao = _status_interacao_evento(evento)
    if status_interacao == "cancelado":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Esta sessão foi cancelada e não aceita novas confirmações.",
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Sessão cancelada.", show_alert=True)
        return ConversationHandler.END
    if status_interacao == "ocorrido":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "ℹ️ Esta sessão já ocorreu e não aceita novas confirmações.",
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Esta sessão já ocorreu.", show_alert=True)
        return ConversationHandler.END

    if not membro:
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "id_evento": id_evento,
            "tipo_ágape": tipo_ágape
        }
        teclado = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Fazer cadastro", callback_data="iniciar_cadastro")]])
        sucesso_privado = await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            CONFIRMACAO_SEM_CADASTRO,
            teclado,
            limpar_conteudo=True
        )

        if not sucesso_privado and update.effective_chat.type in ["group", "supergroup"]:
            link_privado = _link_privado_bot(context, "cadastro")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=CONFIRMACAO_FALLBACK_GRUPO_CADASTRO,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📩 Abrir privado do bot", url=link_privado)]]
                ),
            )
            await _responder_callback_seguro(
                query,
                CONFIRMACAO_CALLBACK_ABRIR_PRIVADO_CADASTRO,
                show_alert=True,
            )
        return ConversationHandler.END

    # Verificar confirmação existente (agora cacheada)
    if buscar_confirmação(id_evento, user_id):
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            JA_CONFIRMOU,
            InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")
            ]]),
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Você já confirmou. Verifique seu privado.")
        return ConversationHandler.END

    participacao_ágape = "Confirmada" if tipo_ágape != "sem" else "Não"
    confirmou_com_ágape = tipo_ágape != "sem"
    desc_ágape = {
        "gratuito": "Gratuito",
        "pago": "Pago",
        "com": "Com ágape",
    }.get(tipo_ágape, "Não aplicável")
    texto_participacao = _texto_participacao_ágape(tipo_ágape)

    dados_confirmação = {
        "id_evento": id_evento,
        "telegram_id": str(user_id),
        "nome": membro.get("Nome", ""),
        "grau": normalizar_grau_nome(membro.get("Grau", "")),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "número_loja": membro.get("Número da loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "ágape": f"{participacao_ágape} ({desc_ágape})",
        "veneravel_mestre": membro.get("Venerável Mestre", ""),
    }
    registrar_confirmação(dados_confirmação)

    # Verificar se o usuário é o secretário do evento
    secretario_id = obter_secretario_responsavel_evento(evento)
    eh_secretario = secretario_id == user_id

    # Notificar secretário apenas se não for o próprio usuário
    if not eh_secretario:
        await notificar_secretario(context, evento, membro, tipo_ágape)

    data = str(evento.get("Data do evento", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    número_loja = str(evento.get("Número da loja", "") or "").strip()
    horario = str(evento.get("Hora", "") or "").strip()
    número_fmt = f" {número_loja}" if número_loja else ""

    bloco_importancia = f"{MENSAGEM_CONFIRMACAO_AGAPE}\n\n" if confirmou_com_ágape else ""

    if eh_secretario:
        # Mensagem combinada para secretário
        resposta = CONFIRMACAO_SECRETARIO_TMPL.format(
            nome=membro.get('Nome', ''),
            data=data,
            loja=nome_loja,
            número_fmt=número_fmt,
            horario=horario,
            participacao=texto_participacao,
            bloco_importancia=bloco_importancia,
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
        if confirmou_com_ágape:
            resposta = CONFIRMACAO_COM_AGAPE_TMPL.format(
                nome=membro.get('Nome', ''),
                data=data,
                loja=nome_loja,
                número_fmt=número_fmt,
                horario=horario,
                participacao=texto_participacao,
                msg_ágape=MENSAGEM_CONFIRMACAO_AGAPE,
            )
        else:
            resposta = CONFIRMACAO_SEM_AGAPE_TMPL.format(
                nome=membro.get('Nome', ''),
                data=data,
                loja=nome_loja,
                número_fmt=número_fmt,
                horario=horario,
                participacao=texto_participacao,
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
    await enviar_dica_contextual(update, context, "confirmação_presença")

    if update.effective_chat.type in ["group", "supergroup"]:
        await _responder_callback_seguro(query, "✅ Presença confirmada! Verifique seu privado.")

    return ConversationHandler.END


# Função auxiliar para continuar confirmação após cadastro
async def iniciar_confirmação_presença_pos_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE, pos: dict):
    user_id = update.effective_user.id
    id_evento = pos.get("id_evento")
    tipo_ágape = pos.get("tipo_ágape", "sem")

    if not id_evento:
        return

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await context.bot.send_message(
            chat_id=user_id,
            text=CONFIRMACAO_SESSAO_NAO_ENCONTRADA
        )
        return

    status_interacao = _status_interacao_evento(evento)
    if status_interacao == "cancelado":
        await context.bot.send_message(
            chat_id=user_id,
            text="⛔ Esta sessão foi cancelada e não aceita novas confirmações."
        )
        return
    if status_interacao == "ocorrido":
        await context.bot.send_message(
            chat_id=user_id,
            text="ℹ️ Esta sessão já ocorreu e não aceita novas confirmações."
        )
        return

    membro = buscar_membro(user_id)
    if not membro:
        return

    if buscar_confirmação(id_evento, user_id):
        await context.bot.send_message(
            chat_id=user_id,
            text=CONFIRMACAO_JA_CONFIRMADO_POS_CADASTRO,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
                [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
            ])
        )
        return

    participacao_ágape = "Confirmada" if tipo_ágape != "sem" else "Não"
    confirmou_com_ágape = tipo_ágape != "sem"
    desc_ágape = {
        "gratuito": "Gratuito",
        "pago": "Pago",
        "com": "Com ágape",
    }.get(tipo_ágape, "Não aplicável")
    texto_participacao = _texto_participacao_ágape(tipo_ágape)

    dados_confirmação = {
        "id_evento": id_evento,
        "telegram_id": str(user_id),
        "nome": membro.get("Nome", ""),
        "grau": normalizar_grau_nome(membro.get("Grau", "")),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "número_loja": membro.get("Número da loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "ágape": f"{participacao_ágape} ({desc_ágape})",
        "veneravel_mestre": membro.get("Venerável Mestre", ""),
    }
    registrar_confirmação(dados_confirmação)

    await notificar_secretario(context, evento, membro, tipo_ágape)

    data = str(evento.get("Data do evento", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    número_loja = str(evento.get("Número da loja", "") or "").strip()
    horario = str(evento.get("Hora", "") or "").strip()
    número_fmt = f" {número_loja}" if número_loja else ""

    if confirmou_com_ágape:
        resposta = CONFIRMACAO_COM_AGAPE_TMPL.format(
            nome=membro.get('Nome', ''),
            data=data,
            loja=nome_loja,
            número_fmt=número_fmt,
            horario=horario,
            participacao=texto_participacao,
            msg_ágape=MENSAGEM_CONFIRMACAO_AGAPE,
        )
    else:
        resposta = CONFIRMACAO_SEM_AGAPE_TMPL.format(
            nome=membro.get('Nome', ''),
            data=data,
            loja=nome_loja,
            número_fmt=número_fmt,
            horario=horario,
            participacao=texto_participacao,
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
    await enviar_dica_contextual(update, context, "confirmação_presença")


# ============================================
# CANCELAMENTO DE PRESENÇA (CORRIGIDO COM IMPORTAÇÕES)
# ============================================

async def cancelar_presença(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa o cancelamento de presença."""
    query = update.callback_query
    data = query.data

    # CASO 1: Confirmação de cancelamento (passo 2)
    if data.startswith("confirma_cancelar|"):
        _, id_evento_cod = data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id
        eventos = listar_eventos() or []
        evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

        logger.info(f"Processando confirmação de cancelamento: evento {id_evento}, usuário {user_id}")

        if evento:
            status_interacao = _status_interacao_evento(evento)
            if status_interacao == "cancelado":
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    "⛔ Esta sessão foi cancelada.",
                    limpar_conteudo=True
                )
                await query.answer("Sessão cancelada.", show_alert=True)
                return
            if status_interacao == "ocorrido":
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    "ℹ️ Esta sessão já ocorreu. Não é mais possível cancelar presença.",
                    limpar_conteudo=True
                )
                await query.answer("Esta sessão já ocorreu.", show_alert=True)
                return

        if cancelar_confirmação(id_evento, user_id):
            # Feedback visual IMEDIATO
            if update.effective_chat.type in ["group", "supergroup"]:
                # No grupo: apaga a lista e mostra mensagem de confirmação
                try:
                    await query.delete_message()
                except Exception as e:
                    logger.debug(f"Aviso ao deletar mensagem de cancelamento: {e}")
                
                # Envia mensagem de confirmação no grupo
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=CANCELAR_PRESENCA_SUCESSO_GRUPO,
                    parse_mode="Markdown"
                )
            else:
                # No privado: edita a mensagem com confirmação
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    PRESENCA_CANCELADA,
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
                    ]),
                    limpar_conteudo=True
                )
            await query.answer("✅ Presença cancelada!")
        else:
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                NAO_CONFIRMOU,
                limpar_conteudo=True
            )
        return

    # CASO 2: Pedido de cancelamento (passo 1)
    if data.startswith("cancelar|"):
        _, id_evento_cod = data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id
        eventos = listar_eventos() or []
        evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

        logger.info(f"Processando pedido de cancelamento: evento {id_evento}, usuário {user_id}")

        if evento:
            status_interacao = _status_interacao_evento(evento)
            if status_interacao == "cancelado":
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    "⛔ Esta sessão foi cancelada.",
                    limpar_conteudo=True
                )
                await query.answer("Sessão cancelada.", show_alert=True)
                return
            if status_interacao == "ocorrido":
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    "ℹ️ Esta sessão já ocorreu. Não é mais possível cancelar presença.",
                    limpar_conteudo=True
                )
                await query.answer("Esta sessão já ocorreu.", show_alert=True)
                return

        # Se estiver em grupo, redireciona para o privado para confirmação
        if update.effective_chat.type in ["group", "supergroup"]:
            teclado = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar|{_encode_cb(id_evento)}"),
                InlineKeyboardButton("🔙 Não, voltar", callback_data=f"evento|{_encode_cb(id_evento)}")
            ]])
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=CANCELAR_PRESENCA_CONFIRMAR,
                    parse_mode="Markdown",
                    reply_markup=teclado
                )
                await _responder_callback_seguro(query, CANCELAR_PRESENCA_CALLBACK_INSTRUCOES)
            except Forbidden:
                link_privado = _link_privado_bot(context, "start")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=CANCELAR_PRESENCA_FALLBACK_GRUPO,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("📩 Abrir privado do bot", url=link_privado)]]
                    ),
                )
                await _responder_callback_seguro(
                    query,
                    CANCELAR_PRESENCA_CALLBACK_ABRIR_PRIVADO,
                    show_alert=True,
                )
            return

        # Se estiver no privado, já pode cancelar direto
        if cancelar_confirmação(id_evento, user_id):
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                PRESENCA_CANCELADA,
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
                ]),
                limpar_conteudo=True
            )
        else:
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                NAO_CONFIRMOU,
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
                ]),
                limpar_conteudo=True
            )
        return

    await _enviar_ou_editar_mensagem(
        context, update.effective_user.id, TIPO_RESULTADO,
        "Comando de cancelamento invalido.",
        limpar_conteudo=True
    )


# ============================================
# LISTA DE CONFIRMADOS
# ============================================

async def ver_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("Buscando lista de confirmados...")

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        titulo = "CONFIRMADOS"
        data_evento = ""
    else:
        nome_loja = str(evento.get("Nome da loja", "") or "").strip()
        data_evento = str(evento.get("Data do evento", "") or "").strip()
        titulo = f"CONFIRMADOS - {nome_loja}"

    confirmações = listar_confirmações_por_evento(id_evento) or []

    linhas: List[str] = []
    for c in confirmações:
        tid = _tid_to_int(c.get("Telegram ID") or c.get("telegram_id"))
        membro = buscar_membro(tid) if tid is not None else None

        if membro:
            linhas.append(montar_linha_confirmado(membro))
        else:
            snapshot = {
                "Grau": c.get("Grau", c.get("grau", "")),
                "Nome": c.get("Nome", c.get("nome", "")),
                "Loja": c.get("Loja", c.get("loja", "")),
                "N\u00famero da loja": c.get("N\u00famero da loja", c.get("número_loja", "")),
                "Oriente": c.get("Oriente", c.get("oriente", "")),
                "Pot\u00eancia": c.get("Pot\u00eancia", c.get("potencia", "")),
                "Vener\u00e1vel Mestre": c.get("Vener\u00e1vel Mestre", c.get("veneravel_mestre", "")),
            }
            linhas.append(montar_linha_confirmado(snapshot))

    corpo = "Nenhuma presença confirmada ate o momento." if not linhas else "\n".join(linhas)
    texto = f"*{titulo}*\n{data_evento}\n\n{corpo}"

    user_id = update.effective_user.id
    ja_confirmou = buscar_confirmação(id_evento, user_id)

    botoes = []
    if ja_confirmou:
        botoes.append([InlineKeyboardButton("\u274C Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    else:
        ágape_evento = str((evento or {}).get("\u00c1gape", "") or "")
        botoes.extend(_teclado_confirmação_evento(id_evento, ágape_evento))

    botoes.append([InlineKeyboardButton("Fechar", callback_data="fechar_mensagem")])

    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )

    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        asyncio.create_task(
            _auto_delete_message(
                context,
                update.effective_chat.id,
                msg.message_id,
                delay=15,
            )
        )


# ============================================
# MINHAS CONFIRMACOES
# ============================================

async def minhas_confirmações(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    qtd_futuras = contar_confirmações_futuras(user_id)

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"\U0001F4C5 Próximas sessões ({qtd_futuras})", callback_data="minhas_confirmações_futuro")],
        [InlineKeyboardButton("\U0001F4DC Histórico", callback_data="minhas_confirmações_historico")],
        [InlineKeyboardButton("\U0001F519 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Minhas Presenças",
        "\u2705 *Minhas Presenças*\n\nConsulte suas confirmações futuras ou o seu historico:",
        teclado
    )


async def minhas_confirmações_futuro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    eventos = listar_eventos() or []
    eventos = _eventos_ordenados(eventos)

    agora = datetime.now()

    confirmados = []
    for ev in eventos:
        id_evento = normalizar_id_evento(ev)
        if buscar_confirmação(id_evento, user_id):
            if _status_interacao_evento(ev, agora) == "disponivel":
                confirmados.append(ev)

    if not confirmados:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "\U0001F4C5 *Próximas Sessões Confirmadas*\n\nVocê ainda não possui sessões futuras confirmadas.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F4C5 Ver Sessões", callback_data="ver_eventos")],
                [InlineKeyboardButton("\U0001F519 Voltar", callback_data="minhas_confirmações")],
            ]),
            limpar_conteudo=True
        )
        return

    botoes = []
    for ev in confirmados[:MAX_EVENTOS_LISTA]:
        id_evento = normalizar_id_evento(ev)
        label = _linha_botao_evento(ev)
        botoes.append([InlineKeyboardButton(label, callback_data=f"detalhes_confirmado|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("\U0001F519 Voltar", callback_data="minhas_confirmações")])

    await navegar_para(
        update, context,
        "Minhas Presenças > Próximas",
        "\U0001F4C5 *Próximas Sessões Confirmadas*\n\nSelecione uma sessão para ver detalhes ou cancelar sua presença:",
        InlineKeyboardMarkup(botoes)
    )


async def minhas_confirmações_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    eventos = listar_eventos() or []
    eventos = _eventos_ordenados(eventos)

    agora = datetime.now()

    confirmados = []
    for ev in eventos:
        id_evento = normalizar_id_evento(ev)
        if buscar_confirmação(id_evento, user_id):
            if _status_interacao_evento(ev, agora) == "ocorrido":
                confirmados.append(ev)

    if not confirmados:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "\U0001F4DC *Histórico*\n\nVocê ainda não participou de nenhuma sessão.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("\U0001F519 Voltar", callback_data="minhas_confirmações")
            ]]),
            limpar_conteudo=True
        )
        return

    botoes = []
    for ev in confirmados[:MAX_EVENTOS_LISTA]:
        id_evento = normalizar_id_evento(ev)
        label = _linha_botao_evento(ev)
        botoes.append([InlineKeyboardButton(label, callback_data=f"detalhes_historico|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("\U0001F519 Voltar", callback_data="minhas_confirmações")])

    await navegar_para(
        update, context,
        "Minhas Presenças > Histórico",
        "\U0001F4DC *Histórico de Presenças*\n\nAqui estao suas participacoes anteriores:",
        InlineKeyboardMarkup(botoes)
    )
    if status_msg:
        texto += f"\n\n{status_msg}"

    linhas_teclado = []
    if _status_interacao_evento(evento) == "disponivel":
        linhas_teclado.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    linhas_teclado.append([InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmações_futuro")])
    teclado = InlineKeyboardMarkup(linhas_teclado)

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
    número = str(evento.get("Número da loja", "") or "").strip()
    número_fmt = f" {número}" if número else ""
    data_txt = str(evento.get("Data do evento", "") or "").strip()
    hora = str(evento.get("Hora", "") or "").strip()
    oriente = str(evento.get("Oriente", "") or "").strip()
    potencia = str(evento.get("Potência", "") or "").strip()

    user_id = update.effective_user.id
    confirmação = buscar_confirmação(id_evento, user_id)
    ágape_info = ""
    if confirmação:
        ágape = confirmação.get("Ágape", "")
        if ágape:
            ágape_info = f"\n🍽 *Ágape:* {ágape}"

    texto = (
        f"🏛 *{nome}{número_fmt}*\n"
        f"📅 {data_txt}\n"
        f"🕕 {hora}\n"
        f"📍 {oriente}\n"
        f"⚜️ {potencia}{ágape_info}\n\n"
        "_Esta sessão já aconteceu._"
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Voltar", callback_data="minhas_confirmações_historico")],
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

confirmação_presença_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmação_presença, pattern=r"^confirmar\|")],
    states={},
    fallbacks=[CommandHandler("cancelar", cancelar_presença)],
)
