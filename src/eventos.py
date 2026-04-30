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
    registrar_confirmacao,
    cancelar_confirmacao,
    buscar_confirmacao,
    listar_confirmacoes_por_evento,
    listar_confirmacoes_por_eventos,
    buscar_confirmacao_em_eventos,
    atualizar_evento,
    get_notificacao_status,
    listar_notificacoes_secretario_pendentes,
    listar_secretarios_com_notificacoes_pendentes,
    registrar_notificacao_secretario_pendente,
    remover_notificacoes_secretario_pendentes,
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
    CONFIRMACAO_GRAU_INSUFICIENTE_TMPL,
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

# Alternativa em memória para instalações que ainda não possuem a coluna
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
        linhas.append(
            f"{i}. {item.get('nome', 'Irmão')} | {item.get('data', '')} - {item.get('loja', '')} | {item.get('agape', '')}"
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
        logger.debug("Nao foi possivel autoapagar mensagem %s no chat %s: %s", message_id, chat_id, e)


def registrar_post_evento_grupo(id_evento: str, chat_id: int, message_id: int) -> None:
    """Registra em memória a mensagem do evento no grupo (alternativa sem coluna persistida)."""
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
    numero = _escape_md(evento.get("Número da loja", ""))
    numero_fmt = f" {numero}" if numero and numero != "0" else ""
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
    agape = _escape_md(evento.get("Ágape", ""))
    endereco_raw = "" if evento.get("Endereço da sessão") is None else str(evento.get("Endereço da sessão")).strip()
    endereco = _escape_md(endereco_raw)
    url_local = _normalizar_url_local(endereco_raw)
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
        f"{nome}{numero_fmt}\n"
        f"{oriente} - {potencia}\n\n"
        "SESSÃO\n"
        f"Tipo: {tipo}\n"
        f"Rito: {rito}\n"
        f"Traje: {traje}\n"
        f"Ágape: {agape}\n\n"
        "ORDEM DO DIA / OBSERVAÇÕES\n"
        f"{observacao}\n\n"
    )

    if url_local:
        texto += f"Local: [Abrir no mapa]({url_local})"
    else:
        texto += f"Local: {endereco}"

    if status == "cancelado":
        texto += "\n\n⛔ *STATUS:* CANCELADO"
    return texto


def montar_teclado_publicacao_evento(evento: dict) -> Optional[InlineKeyboardMarkup]:
    """Monta teclado do card publicado no grupo conforme status atual."""
    status = str(evento.get("Status", "") or "").strip().lower()
    if status == "cancelado":
        return None

    id_evento = normalizar_id_evento(evento)
    agape = str(evento.get("Ágape", "") or "")
    endereco_raw = "" if evento.get("Endereço da sessão") is None else str(evento.get("Endereço da sessão")).strip()
    url_local = _normalizar_url_local(endereco_raw)
    linhas = _teclado_confirmacao_evento(id_evento, agape)
    linhas.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")])
    # Cancelamento é visível para todos (teclado inline é global no Telegram).
    # Se o usuário não estiver confirmado, o handler responde com um toast amigável.
    linhas.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar_card|{_encode_cb(id_evento)}")])
    if url_local:
        linhas.append([InlineKeyboardButton("📍 Abrir no mapa", url=url_local)])
    return InlineKeyboardMarkup(linhas)


async def sincronizar_resumo_evento_grupo(context: ContextTypes.DEFAULT_TYPE, evento: dict) -> bool:
    """Atualiza o card original do evento no grupo após edição de dados/status."""
    id_evento = normalizar_id_evento(evento)
    grupo_id = _tid_to_int(evento.get("Telegram ID do grupo") or evento.get("grupo_telegram_id"))
    msg_id = _tid_to_int(evento.get("Telegram Message ID do grupo") or evento.get("grupo_mensagem_id"))

    async def _publicar_novo_card() -> bool:
        """Alternativa para eventos legados sem message_id: publica novo card e persiste o ID."""
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

    # Alternativa para ambientes sem persistência do message_id no banco.
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


def _grau_base_para_hierarquia(valor: str) -> str:
    grau = normalizar_grau_nome(valor)
    if grau == "Mestre Instalado":
        return GRAU_MESTRE
    return grau


def _hierarquia_grau(valor: str) -> int:
    grau = _grau_base_para_hierarquia(valor)
    ordem = {
        GRAU_APRENDIZ: 1,
        GRAU_COMPANHEIRO: 2,
        GRAU_MESTRE: 3,
    }
    return ordem.get(grau, 999)


def _pode_confirmar_presenca(grau_cadastrado: str, grau_sessao: str) -> bool:
    return _hierarquia_grau(grau_cadastrado) >= _hierarquia_grau(grau_sessao)


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


def _id_evento_legado(ev: dict) -> str:
    """ID determinístico legado (usado antes de existir `ID Evento`)."""
    return f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"


def _ids_evento_aliases(id_evento: str, evento: Optional[dict]) -> List[str]:
    ids: List[str] = []
    if id_evento:
        ids.append(str(id_evento))
    if evento:
        ids.append(normalizar_id_evento(evento))
        ids.append(_id_evento_legado(evento))

    out: List[str] = []
    for raw in ids:
        s = str(raw or "").strip()
        if not s or s.lower() == "nan":
            continue
        if s not in out:
            out.append(s)
    return out


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


def _eh_mi(dados: dict) -> bool:
    for k in ("Mestre Instalado", "mestre_instalado", "mi"):
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
    if _eh_mi(dados_membro_ou_snapshot) and grau == GRAU_MESTRE:
        grau = f"{grau} (MI)"

    loja = (dados_membro_ou_snapshot.get("Loja") or dados_membro_ou_snapshot.get("loja") or "").strip()
    numero = (
        dados_membro_ou_snapshot.get("Número da loja")
        or dados_membro_ou_snapshot.get("NÃºmero da loja")
        or dados_membro_ou_snapshot.get("numero_loja")
        or ""
    )
    numero = str(numero).strip()

    oriente = (dados_membro_ou_snapshot.get("Oriente") or dados_membro_ou_snapshot.get("oriente") or "").strip()
    potencia = (
        dados_membro_ou_snapshot.get("Potência")
        or dados_membro_ou_snapshot.get("Potęncia")
        or dados_membro_ou_snapshot.get("PotÃªncia")
        or dados_membro_ou_snapshot.get("potencia")
        or ""
    ).strip()

    loja_composta = f"{loja} {numero}".strip()
    return f"{nome} - {grau} - {loja_composta} - {oriente} - {potencia}"


def _status_evento_normalizado(evento: Optional[dict]) -> str:
    return str((evento or {}).get("Status", "") or "").strip().lower()


def _data_hora_evento(evento: Optional[dict]) -> Optional[datetime]:
    if not evento:
        return None
    data_base = parse_data_evento(evento.get("Data do evento", ""))
    if not data_base:
        return None
    hh, mm = _parse_hora(evento.get("Hora", ""))
    return data_base.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _motivo_bloqueio_confirmacao(evento: Optional[dict]) -> Optional[str]:
    if not evento:
        return EVENTO_NAO_ENCONTRADO

    if _status_evento_normalizado(evento) == "cancelado":
        return "⛔ Esta sessão foi cancelada e não aceita mais confirmações."

    data_hora_evento = _data_hora_evento(evento)
    if data_hora_evento and data_hora_evento < datetime.now():
        return "⌛ Esta sessão já ocorreu e não aceita novas confirmações."

    return None


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

    texto = NOTIFICACAO_NOVA_CONFIRMACAO.format(
        nome=nome_membro,
        data=data,
        loja=f"{nome_loja}{numero_fmt}",
        agape=texto_participacao,
    )

    item_pendente = {
        "nome": nome_membro,
        "data": str(data or ""),
        "loja": f"{nome_loja}{numero_fmt}",
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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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
        f"🔺 *Grau da sessão:* {grau}\n"
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
        texto += f"\n\n📌 *Ordem do dia / observações:* {obs}"

    user_id = update.effective_user.id
    ids_aliases = _ids_evento_aliases(id_evento, evento)
    ja_confirmou = buscar_confirmacao_em_eventos(ids_aliases, user_id)
    botoes = []
    motivo_bloqueio = _motivo_bloqueio_confirmacao(evento)

    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    elif not motivo_bloqueio:
        botoes.extend(_teclado_confirmacao_evento(id_evento, agape))

    if motivo_bloqueio:
        texto += f"\n\n{motivo_bloqueio}"

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
        return next(
            (
                ev
                for ev in eventos
                if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
            ),
            None,
        )
    
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

    # Compatibilidade: aceita confirmações antigas gravadas com ID legado.
    ids_aliases = _ids_evento_aliases(id_evento, evento)

    # Canoniza o ID para gravação e callbacks futuros (quando existir `ID Evento`).
    id_evento_canon = normalizar_id_evento(evento)
    if id_evento_canon and id_evento_canon != id_evento:
        id_evento = id_evento_canon

    motivo_bloqueio = _motivo_bloqueio_confirmacao(evento)
    if motivo_bloqueio:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            motivo_bloqueio,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")],
                [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
            ]),
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, motivo_bloqueio, show_alert=True)
        return ConversationHandler.END

    if not membro:
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "id_evento": id_evento,
            "tipo_agape": tipo_agape
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

    # Verificar confirmação existente (evita duplicidade e dá feedback amigável).
    if buscar_confirmacao_em_eventos(ids_aliases, user_id):
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Irmão, você já confirmou presença.")
            return ConversationHandler.END

        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Irmão, você já confirmou presença.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("👥 Ver lista", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")
            ]]),
            limpar_conteudo=True
        )
        return ConversationHandler.END

    grau_cadastrado = normalizar_grau_nome(membro.get("Grau", ""))
    grau_sessao = normalizar_grau_nome(evento.get("Grau", ""))
    if not _pode_confirmar_presenca(grau_cadastrado, grau_sessao):
        await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            CONFIRMACAO_GRAU_INSUFICIENTE_TMPL.format(
                grau_sessao=grau_sessao or "não informado",
                grau_cadastrado=grau_cadastrado or "não informado",
            ),
            InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Ver meu cadastro", callback_data="meu_cadastro")],
                [InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")],
            ]),
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Verifique seu privado.", show_alert=True)
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
        "mestre_instalado": membro.get("Mestre Instalado", ""),
    }
    ok = registrar_confirmacao(dados_confirmacao)
    if not ok:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚠️ Não consegui registrar sua confirmação agora. Tente novamente em instantes.",
            InlineKeyboardMarkup([[InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")]]),
            limpar_conteudo=True,
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Falha ao confirmar. Tente novamente.", show_alert=True)
        return ConversationHandler.END

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
        resposta = CONFIRMACAO_SECRETARIO_TMPL.format(
            nome=membro.get('Nome', ''),
            data=data,
            loja=nome_loja,
            numero_fmt=numero_fmt,
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
        if confirmou_com_agape:
            resposta = CONFIRMACAO_COM_AGAPE_TMPL.format(
                nome=membro.get('Nome', ''),
                data=data,
                loja=nome_loja,
                numero_fmt=numero_fmt,
                horario=horario,
                participacao=texto_participacao,
                msg_agape=MENSAGEM_CONFIRMACAO_AGAPE,
            )
        else:
            resposta = CONFIRMACAO_SEM_AGAPE_TMPL.format(
                nome=membro.get('Nome', ''),
                data=data,
                loja=nome_loja,
                numero_fmt=numero_fmt,
                horario=horario,
                participacao=texto_participacao,
            )

        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
        ])

    sucesso_privado = await _enviar_ou_editar_mensagem(
        context,
        user_id,
        TIPO_RESULTADO,
        resposta,
        teclado,
        limpar_conteudo=True,
    )
    await enviar_dica_contextual(update, context, "confirmacao_presenca")

    if update.effective_chat.type in ["group", "supergroup"]:
        if sucesso_privado:
            await _responder_callback_seguro(query, "✅ Presença confirmada!")
        else:
            link_privado = _link_privado_bot(context, "start")
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="✅ Presença confirmada.\n\nNão consegui te enviar no privado. Abra o bot para ver os detalhes.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Abrir privado do bot", url=link_privado)]]),
                )
            except Exception as e:
                logger.debug("Falha ao enviar fallback no grupo após confirmação: %s", e)
            await _responder_callback_seguro(query, "Abra o privado do bot para ver os detalhes.", show_alert=True)

    return ConversationHandler.END


# Função auxiliar para continuar confirmação após cadastro
async def iniciar_confirmacao_presenca_pos_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE, pos: dict):
    user_id = update.effective_user.id
    id_evento = pos.get("id_evento")
    tipo_agape = pos.get("tipo_agape", "sem")

    if not id_evento:
        return

    eventos = listar_eventos() or []
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )
    if not evento:
        await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            CONFIRMACAO_SESSAO_NAO_ENCONTRADA,
            limpar_conteudo=True,
        )
        return

    motivo_bloqueio = _motivo_bloqueio_confirmacao(evento)
    if motivo_bloqueio:
        await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            motivo_bloqueio,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
            ]),
            limpar_conteudo=True,
        )
        return

    membro = buscar_membro(user_id)
    if not membro:
        return

    ids_aliases = _ids_evento_aliases(id_evento, evento)
    id_evento_canon = normalizar_id_evento(evento)
    if id_evento_canon and id_evento_canon != id_evento:
        id_evento = id_evento_canon

    if buscar_confirmacao_em_eventos(ids_aliases, user_id):
        await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            CONFIRMACAO_JA_CONFIRMADO_POS_CADASTRO,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
                [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
            ]),
            limpar_conteudo=True,
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
        "mestre_instalado": membro.get("Mestre Instalado", ""),
    }
    ok = registrar_confirmacao(dados_confirmacao)
    if not ok:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚠️ Não consegui registrar sua confirmação agora. Tente novamente em instantes.",
            InlineKeyboardMarkup([[InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")]]),
            limpar_conteudo=True,
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Falha ao confirmar. Tente novamente.", show_alert=True)
        return

    await notificar_secretario(context, evento, membro, tipo_agape)

    data = str(evento.get("Data do evento", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    numero_loja = str(evento.get("Número da loja", "") or "").strip()
    horario = str(evento.get("Hora", "") or "").strip()
    numero_fmt = f" {numero_loja}" if numero_loja else ""

    if confirmou_com_agape:
        resposta = CONFIRMACAO_COM_AGAPE_TMPL.format(
            nome=membro.get('Nome', ''),
            data=data,
            loja=nome_loja,
            numero_fmt=numero_fmt,
            horario=horario,
            participacao=texto_participacao,
            msg_agape=MENSAGEM_CONFIRMACAO_AGAPE,
        )
    else:
        resposta = CONFIRMACAO_SEM_AGAPE_TMPL.format(
            nome=membro.get('Nome', ''),
            data=data,
            loja=nome_loja,
            numero_fmt=numero_fmt,
            horario=horario,
            participacao=texto_participacao,
        )

    await _enviar_ou_editar_mensagem(
        context,
        user_id,
        TIPO_RESULTADO,
        resposta,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
        ]),
        limpar_conteudo=True,
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

        eventos = listar_eventos() or []
        evento = next(
            (
                ev
                for ev in eventos
                if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
            ),
            None,
        )
        ids_aliases = _ids_evento_aliases(id_evento, evento)

        cancelou = False
        for eid in ids_aliases:
            if cancelar_confirmacao(eid, user_id):
                cancelou = True

        if cancelou:
            if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
                await _responder_callback_seguro(query, "✅ Presença cancelada.")
                try:
                    await _enviar_ou_editar_mensagem(
                        context, user_id, TIPO_RESULTADO,
                        PRESENCA_CANCELADA,
                        InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]]),
                        limpar_conteudo=True
                    )
                except Exception as e:
                    logger.debug("Falha ao avisar cancelamento no privado: %s", e)
            else:
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    PRESENCA_CANCELADA,
                    InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]]),
                    limpar_conteudo=True
                )
        else:
            if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
                await _responder_callback_seguro(query, "Irmão, você ainda não confirmou sua presença.")
            else:
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    NAO_CONFIRMOU,
                    limpar_conteudo=True
                )
        return

    # CASO 2: Pedido de cancelamento (1 clique)
    if data.startswith("cancelar|") or data.startswith("cancelar_card|"):
        _, id_evento_cod = data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        logger.info(f"Processando pedido de cancelamento: evento {id_evento}, usuário {user_id}")

        # Cancela direto (grupo e privado)
        eventos = listar_eventos() or []
        evento = next(
            (
                ev
                for ev in eventos
                if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
            ),
            None,
        )
        ids_aliases = _ids_evento_aliases(id_evento, evento)

        if not buscar_confirmacao_em_eventos(ids_aliases, user_id):
            if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
                await _responder_callback_seguro(query, "Irmão, você ainda não confirmou sua presença.")
                return

            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "Irmão, você ainda não confirmou sua presença.",
                InlineKeyboardMarkup([[InlineKeyboardButton("👥 Ver lista", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")]]),
                limpar_conteudo=True
            )
            return

        cancelou = False
        for eid in ids_aliases:
            if cancelar_confirmacao(eid, user_id):
                cancelou = True

        if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
            await _responder_callback_seguro(query, "✅ Presença cancelada.")

            # Se o clique foi na lista de confirmados, tenta atualizar a mensagem silenciosamente.
            try:
                texto_atual = (getattr(query.message, "text", None) or "").strip()
                if texto_atual.startswith("*CONFIRMADOS"):
                    nome_loja = str((evento or {}).get("Nome da loja", "") or "").strip()
                    data_evento = str((evento or {}).get("Data do evento", "") or "").strip()
                    titulo = "CONFIRMADOS" if not nome_loja else f"CONFIRMADOS - {nome_loja}"

                    confirmacoes = listar_confirmacoes_por_eventos(ids_aliases) or []
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
                                "Número da loja": c.get("Número da loja", c.get("numero_loja", c.get("NÃƒÂºmero da loja", ""))),
                                "Oriente": c.get("Oriente", c.get("oriente", "")),
                                "Potência": c.get("Potência", c.get("potencia", c.get("PotÃƒÂªncia", ""))),
                                "Venerável Mestre": c.get("Venerável Mestre", c.get("veneravel_mestre", c.get("VenerÃƒÂ¡vel Mestre", ""))),
                            }
                            linhas.append(montar_linha_confirmado(snapshot))

                    corpo = "Nenhuma presença confirmada até o momento." if not linhas else "\n".join(linhas)
                    texto = f"*{titulo}*\n{data_evento}\n\n{corpo}"

                    agape_evento = str((evento or {}).get("Ágape", "") or "")
                    botoes = []
                    botoes.extend(_teclado_confirmacao_evento(id_evento, agape_evento))
                    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])

                    await query.edit_message_text(
                        text=texto,
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(botoes),
                    )
            except Exception as e:
                logger.debug("Falha ao atualizar lista de confirmados após cancelamento: %s", e)

            # Informa no privado sem pedir confirmação (silencioso no grupo)
            try:
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    PRESENCA_CANCELADA,
                    InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]]),
                    limpar_conteudo=True
                )
            except Exception as e:
                logger.debug("Falha ao avisar cancelamento no privado: %s", e)
            return

        if cancelou:
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
    await _responder_callback_seguro(query, "👥 Buscando lista de confirmados...")

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

    ids_aliases = _ids_evento_aliases(id_evento, evento)
    confirmacoes = listar_confirmacoes_por_eventos(ids_aliases) or []
    if len(ids_aliases) > 1:
        logger.debug("Confirmacoes por alias de evento %s -> %s itens", ids_aliases, len(confirmacoes))

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
                "Número da loja": c.get("Número da loja", c.get("numero_loja", c.get("NÃºmero da loja", ""))),
                "Oriente": c.get("Oriente", c.get("oriente", "")),
                "Potência": c.get("Potência", c.get("potencia", c.get("PotÃªncia", ""))),
                "Venerável Mestre": c.get("Venerável Mestre", c.get("veneravel_mestre", c.get("VenerÃ¡vel Mestre", ""))),
            }
            linhas.append(montar_linha_confirmado(snapshot))

    corpo = "Nenhuma presença confirmada até o momento." if not linhas else "\n".join(linhas)
    texto = f"*{titulo}*\n{data_evento}\n\n{corpo}"

    user_id = update.effective_user.id
    ja_confirmou = buscar_confirmacao_em_eventos(ids_aliases, user_id)

    botoes = []
    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    else:
        agape_evento = str((evento or {}).get("Ágape", "") or "")
        botoes.extend(_teclado_confirmacao_evento(id_evento, agape_evento))

    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])

    reply_markup = InlineKeyboardMarkup(botoes)

    if update.effective_chat and update.effective_chat.type == "private":
        await _enviar_ou_editar_mensagem(
            context,
            update.effective_user.id,
            TIPO_RESULTADO,
            texto,
            reply_markup,
            limpar_conteudo=True,
        )
    else:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

        # No grupo, a lista completa é temporária para evitar poluição visual.
        # O resumo é independente e permanece visível.
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
        if buscar_confirmacao_em_eventos([id_evento, _id_evento_legado(ev)], user_id):
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
        if buscar_confirmacao_em_eventos([id_evento, _id_evento_legado(ev)], user_id):
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
    ids_aliases = _ids_evento_aliases(id_evento, evento)
    id_evento_canon = normalizar_id_evento(evento)
    if id_evento_canon and id_evento_canon != id_evento:
        id_evento = id_evento_canon
    confirmacao = buscar_confirmacao_em_eventos(ids_aliases, user_id)
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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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
    ids_aliases = _ids_evento_aliases(id_evento, evento)
    id_evento_canon = normalizar_id_evento(evento)
    if id_evento_canon and id_evento_canon != id_evento:
        id_evento = id_evento_canon
    confirmacao = buscar_confirmacao_em_eventos(ids_aliases, user_id)
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
    if update.effective_chat and update.effective_chat.type == "private":
        await voltar_ao_menu_principal(update, context)
        return
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
