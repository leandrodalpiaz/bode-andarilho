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

from src.ritos import normalizar_rito
from src.location_service import buscar_estados_uf, buscar_cidades_por_uf

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, CommandHandler

from src.sheets_supabase import (
    listar_eventos,
    buscar_membro,
    membro_esta_ativo,
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
from src.potencias import formatar_potencia, potencia_de_dados
from src.evento_midia import editar_ou_republicar_evento_visual, publicar_evento_no_grupo

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
        logger.debug("Não foi possível autoapagar mensagem %s no chat %s: %s", message_id, chat_id, e)


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
TOKEN_POR_RITO_MENU = "por_rito"
TOKEN_POR_LOCALIDADE_MENU = "por_localidade"
TOKEN_POR_POTENCIA_MENU = "por_potencia"
TOKEN_TODAS_DISPONIVEIS = "todas_disponiveis"
TOKEN_POR_DATA_MENU = "por_data_menu"
TOKEN_GEO_RAIO_MENU = "geo_raio_menu"

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
    potencia = _escape_md(formatar_potencia(*potencia_de_dados(evento)))
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
    linhas = _teclado_confirmacao_evento(id_evento, agape)
    linhas.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")])
    # Cancelamento é visível para todos (teclado inline é global no Telegram).
    # Se o usuário não estiver confirmado, o handler responde com um toast amigável.
    linhas.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar_card|{_encode_cb(id_evento)}")])
    
    # Botão de Localização Dinâmico (Coluna 3)
    if endereco_raw:
        if endereco_raw.startswith(("http://", "https://")):
            linhas.append([InlineKeyboardButton("📍 Localização", url=endereco_raw)])
        else:
            linhas.append([InlineKeyboardButton("📍 Localização", callback_data=f"ver_local|{_encode_cb(id_evento)}")])
            
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
            nova_msg, tipo_msg = await publicar_evento_no_grupo(
                context,
                grupo_id,
                evento,
                montar_texto_publicacao_evento(evento),
                montar_teclado_publicacao_evento(evento),
            )
            registrar_post_evento_grupo(id_evento, grupo_id, nova_msg.message_id)

            # Persiste para futuras sincronizações após restart.
            atualizado = atualizar_evento(0, {
                "ID Evento": id_evento,
                "Telegram Message ID do grupo": str(nova_msg.message_id),
                "Telegram tipo mensagem grupo": tipo_msg,
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
        return await editar_ou_republicar_evento_visual(
            context,
            grupo_id,
            msg_id,
            evento,
            montar_texto_publicacao_evento(evento),
            montar_teclado_publicacao_evento(evento),
        )
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
        or dados_membro_ou_snapshot.get("numero_loja")
        or ""
    )
    numero = str(numero).strip()

    oriente = (dados_membro_ou_snapshot.get("Oriente") or dados_membro_ou_snapshot.get("oriente") or "").strip()
    potencia = (
        dados_membro_ou_snapshot.get("Potência")
        or dados_membro_ou_snapshot.get("potencia")
        or ""
    ).strip()

    num_fmt = f" nº {numero}" if numero and str(numero) != "0" else ""
    loja_fmt = f"{loja}{num_fmt}".strip()
    return f"• {nome} - {grau} - {loja_fmt} - {potencia}"


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


def _normalizar_rito(valor: Any) -> str:
    # Compat: retorna o normalizado quando reconhecido; caso contrário, preserva o valor original.
    return normalizar_rito(valor) or str(valor or "").strip()


def _ritos_disponiveis(eventos: List[dict]) -> List[str]:
    ritos: List[str] = []
    for ev in eventos:
        rito = _normalizar_rito(ev.get("Rito") or ev.get("rito"))
        if rito and rito not in ritos:
            ritos.append(rito)
    return sorted(ritos, key=lambda x: x.lower())


def _filtrar_por_rito(eventos: List[dict], rito_nome: str) -> Tuple[str, List[dict]]:
    alvo = _normalizar_rito(rito_nome)
    titulo = f"Sessões — Rito — {alvo}"

    filtrados = []
    for ev in eventos:
        rito = _normalizar_rito(ev.get("Rito") or ev.get("rito"))
        if rito.lower() == alvo.lower():
            filtrados.append(ev)

    return titulo, _eventos_ordenados(filtrados)


def _formatar_data_curta(ev: dict) -> str:
    dt = parse_data_evento(ev.get("Data do evento", ""))
    if not dt:
        return str(ev.get("Data do evento", "") or "").strip() or "Sem data"
    dia_semana = traduzir_dia_abreviado(dt.strftime("%A"))
    return f"{dt.strftime('%d/%m')} ({dia_semana})"


def _linha_botao_evento(ev: dict, omitir_grau: bool = False, omitir_rito: bool = False) -> str:
    """
    Monta uma linha ultracompacta para exibição no botão inline do Telegram,
    omitindo dados de forma inteligente de acordo com o contexto de filtro e
    abreviando nomes longos para evitar o corte da tela (truncamento '...').
    Formato: 📅 DD/MM • Grau • Loja Nº (Pot) • Rito • Hh
    """
    # 1. Data
    dt_obj = parse_data_evento(ev.get("Data do evento", ""))
    data_fmt = dt_obj.strftime("%d/%m") if dt_obj else "?"
    
    # 2. Grau (Abreviação)
    grau_txt = ""
    if not omitir_grau:
        grau_raw = normalizar_grau_nome(ev.get("Grau", ""))
        if grau_raw == GRAU_APRENDIZ:
            grau_txt = "Apr"
        elif grau_raw == GRAU_COMPANHEIRO:
            grau_txt = "Comp"
        elif grau_raw == GRAU_MESTRE:
            grau_txt = "Mest"
        elif "Instalado" in grau_raw:
            grau_txt = "MI"
        else:
            grau_txt = grau_raw[:4]
            
    # 3. Loja e Potência (Compactação)
    nome_loja = str(ev.get("Nome da loja", "") or "").strip()
    if len(nome_loja) > 16:
        # Abrevia palavras longas ou trunca
        palavras = nome_loja.split()
        if len(palavras) > 1:
            nome_loja = " ".join(p[:4] + "." if len(p) > 4 and p.lower() not in ("da","do","de","dos","das") else p for p in palavras)
        if len(nome_loja) > 16:
            nome_loja = nome_loja[:14] + ".."
            
    numero = str(ev.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero and numero != "0" else ""
    
    potencia = formatar_potencia(*potencia_de_dados(ev))
    pot_fmt = f" ({potencia})" if potencia else ""
    
    # 4. Rito (Abreviação)
    rito_txt = ""
    if not omitir_rito:
        rito_raw = _normalizar_rito(ev.get("Rito", ""))
        if rito_raw:
            rl = rito_raw.lower()
            if "escocês" in rl or "reaa" in rl:
                rito_txt = "REAA"
            elif "york" in rl:
                rito_txt = "York"
            elif "brasileiro" in rl:
                rito_txt = "Bras"
            elif "moderno" in rl:
                rito_txt = "Mod"
            elif "schroder" in rl or "schröder" in rl:
                rito_txt = "Schr"
            elif "adonhiramita" in rl:
                rito_txt = "Adon"
            else:
                rito_txt = rito_raw[:4].strip()
                
    # 5. Hora Curta (ex: 20h, 19h30)
    hora_raw = str(ev.get("Hora", "") or "").strip()
    hora_fmt = ""
    if hora_raw:
        partes = hora_raw.split(":")
        hh = partes[0].strip()
        mm = partes[1].strip() if len(partes) > 1 else "00"
        if mm == "00" or mm == "0":
            hora_fmt = f"{hh}h"
        else:
            hora_fmt = f"{hh}:{mm}"
            
    # Monta os componentes omitindo vazios
    componentes = [f"📅 {data_fmt}"]
    if grau_txt:
        componentes.append(grau_txt)
    
    componentes.append(f"{nome_loja}{numero_fmt}{pot_fmt}")
    
    if rito_txt:
        componentes.append(rito_txt)
        
    if hora_fmt:
        componentes.append(hora_fmt)
        
    return " • ".join(componentes)


# ============================================
# FILTROS GEOGRÁFICOS E DE POTÊNCIA (RESOLVEDORES)
# ============================================

def _lojas_map_cache() -> Dict[str, dict]:
    """Retorna dicionário global ID -> LOJA das lojas no cache."""
    from src.sheets_supabase import listar_lojas
    try:
        lojas = listar_lojas(0, include_todas=True) or []
        return {str(l.get("ID") or l.get("id") or ""): l for l in lojas if (l.get("ID") or l.get("id"))}
    except Exception as e:
        logger.warning(f"Erro ao carregar mapa de lojas: {e}")
        return {}

def _resolver_dados_geo_loja(ev: dict, lojas_map: dict) -> Tuple[str, str]:
    """Retorna (estado_uf, cidade) canonizado do evento via Loja associada."""
    loja_id = str(ev.get("ID da loja") or ev.get("loja_id") or "")
    loja = lojas_map.get(loja_id)
    
    if not loja:
        # Fallback: procura por Nome e Número
        nome_ev = str(ev.get("Nome da loja") or ev.get("nome_loja") or "").strip().lower()
        num_ev = str(ev.get("Número da loja") or ev.get("numero_loja") or "").strip()
        for l in lojas_map.values():
            nome_l = str(l.get("Nome da Loja") or l.get("nome_loja") or "").strip().lower()
            num_l = str(l.get("Número") or l.get("numero") or "").strip()
            if nome_ev == nome_l and (not num_ev or num_ev == num_l):
                loja = l
                break
                
    if loja:
        uf = str(loja.get("Estado UF") or loja.get("estado_uf") or "").strip().upper()
        cid = str(loja.get("Cidade") or loja.get("cidade") or "").strip()
        return uf, cid
        
    # Segundo fallback: Caso não encontre, assume o próprio "Oriente" do evento como cidade (antigo)
    cid = str(ev.get("Oriente") or ev.get("oriente") or "").strip()
    return "", cid

def _ufs_ativas_eventos(eventos: List[dict], lojas_map: dict) -> List[str]:
    """Retorna lista de UFs com sessões agendadas."""
    ufs = set()
    for ev in eventos:
        uf, _ = _resolver_dados_geo_loja(ev, lojas_map)
        if uf:
            ufs.add(uf)
    return sorted(list(ufs))

def _cidades_ativas_eventos(eventos: List[dict], lojas_map: dict, uf_alvo: str) -> List[str]:
    """Retorna cidades ativas em uma determinada UF."""
    cidades = set()
    uf_alvo = uf_alvo.upper().strip()
    for ev in eventos:
        uf, cid = _resolver_dados_geo_loja(ev, lojas_map)
        if uf == uf_alvo and cid:
            cidades.add(cid)
    return sorted(list(cidades), key=lambda x: x.lower())

def _potencias_ativas_eventos(eventos: List[dict]) -> List[str]:
    """Retorna a lista de potências com eventos ativos."""
    pots = set()
    for ev in eventos:
        p = str(ev.get("Potência") or ev.get("potencia") or "").strip()
        if p:
            pots.add(p)
    return sorted(list(pots), key=lambda x: x.lower())

def _filtrar_por_cidade(eventos: List[dict], lojas_map: dict, uf: str, cidade: str) -> Tuple[str, List[dict]]:
    titulo = f"Sessões — {cidade} — {uf}"
    filtrados = []
    for ev in eventos:
        ev_uf, ev_cid = _resolver_dados_geo_loja(ev, lojas_map)
        if ev_uf.upper() == uf.upper() and ev_cid.lower() == cidade.lower():
            filtrados.append(ev)
    return titulo, _eventos_ordenados(filtrados)

def _filtrar_por_potencia(eventos: List[dict], potencia_nome: str) -> Tuple[str, List[dict]]:
    titulo = f"Sessões — Potência — {potencia_nome}"
    filtrados = []
    for ev in eventos:
        p = str(ev.get("Potência") or ev.get("potencia") or "").strip()
        if p.lower() == potencia_nome.lower():
            filtrados.append(ev)
    return titulo, _eventos_ordenados(filtrados)


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
    eventos = listar_eventos() or []
    agora = datetime.now()
    
    # Contabiliza apenas eventos ativos no futuro
    total_futuros = 0
    for ev in eventos:
        dt = _data_hora_evento(ev)
        if dt and dt >= agora and _status_evento_normalizado(ev) != "cancelado":
            total_futuros += 1

    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"📋 Sessões Disponíveis ({total_futuros})", callback_data=f"data|{TOKEN_TODAS_DISPONIVEIS}"),
        ],
        [
            InlineKeyboardButton("📅 Por Data", callback_data=f"data|{TOKEN_POR_DATA_MENU}"),
            InlineKeyboardButton("⚖️ Por Grau", callback_data=f"data|{TOKEN_POR_GRAU_MENU}"),
        ],
        [
            InlineKeyboardButton("📜 Por Rito", callback_data=f"data|{TOKEN_POR_RITO_MENU}"),
            InlineKeyboardButton("📍 Por Localização", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}"),
        ],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    texto_busca = (
        "📅 *Como deseja visualizar as sessões?*\n\n"
        "Selecione uma opção acima para explorar a agenda."
    )

    await navegar_para(
        update, context,
        "Ver Sessões",
        texto_busca,
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
    if token_or_data == TOKEN_POR_DATA_MENU:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Esta Semana", callback_data=f"data|{TOKEN_SEMANA_ATUAL}")],
            [InlineKeyboardButton("📅 Neste Mês", callback_data=f"data|{TOKEN_MES_ATUAL}")],
            [InlineKeyboardButton("📅 Próximos Meses", callback_data=f"data|{TOKEN_PROXIMOS_MESES}")],
            [InlineKeyboardButton("🗓️ Calendário Geral", callback_data="calendario|0|0")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")],
        ])
        await navegar_para(
            update, context,
            "Ver Sessões > Por Data",
            "📅 *Filtrar sessões por período:*",
            teclado
        )
        return

    if token_or_data == TOKEN_TODAS_DISPONIVEIS:
        eventos = listar_eventos() or []
        agora = datetime.now()
        filtrados = []
        for ev in eventos:
            dt = _data_hora_evento(ev)
            if dt and dt >= agora and _status_evento_normalizado(ev) != "cancelado":
                filtrados.append(ev)
        
        filtrados.sort(key=lambda x: _data_hora_evento(x) or agora)
        
        if not filtrados:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "📋 *Todas as Sessões Disponíveis*\n\nNão há sessões agendadas no momento.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]])
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
            "Ver Sessões > Todas",
            "📋 *Todas as sessões futuras agendadas:*",
            InlineKeyboardMarkup(botoes)
        )
        return

    if token_or_data.startswith(TOKEN_GEO_RAIO_MENU):
        import re
        from src.sheets_supabase import buscar_membro, buscar_loja_por_id, buscar_loja_por_nome_numero
        from src.location_service import filtrar_locais_por_raio
        
        # Determina o raio solicitado (padrão: 100km)
        partes_geo = token_or_data.split("|")
        raio_km = 100.0
        if len(partes_geo) > 1:
            try:
                raio_km = float(partes_geo[1])
            except:
                raio_km = 100.0
                
        membro = buscar_membro(update.effective_user.id)
        if not membro:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "❌ *Perfil não encontrado*\n\nVocê precisa possuir um registro regular para utilizar a busca geográfica.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]])
            )
            return
            
        oriente_raw = str(membro.get("Oriente") or membro.get("oriente") or "").strip()
        if not oriente_raw or oriente_raw.lower() in ("não informado", "nao informado"):
             await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "⚠️ *Oriente não configurado*\n\nSeu perfil não possui um Oriente (Cidade) cadastrado. Edite seus dados para usar esta função.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]])
            )
             return
             
        # 1. Extração e limpeza do Oriente de Origem (cidade sem o estado no nome)
        cidade_origem = re.split(r"[-/]", oriente_raw)[0].strip()
        
        # 2. Descoberta da UF do membro (via Loja ou extração textual)
        uf_origem = ""
        loja_id = membro.get("ID da loja") or membro.get("loja_id")
        loja = buscar_loja_por_id(loja_id) if loja_id else None
        if not loja:
            l_nome = membro.get("Loja") or membro.get("loja")
            l_num = membro.get("Número da loja") or membro.get("numero_loja")
            if l_nome:
                loja = buscar_loja_por_nome_numero(l_nome, l_num)
        if loja:
            uf_origem = str(loja.get("Estado UF") or loja.get("estado_uf") or "").strip().upper()
            
        if not uf_origem:
            # Fallback: tentar achar match de UF na string do Oriente original (ex: "Torres-RS")
            match = re.search(r"[-/]\s*([A-Za-z]{2})\b", oriente_raw)
            if match:
                uf_origem = match.group(1).upper()
                
        if not uf_origem:
             # Fallback final: Se não tem UF de jeito nenhum, pedimos para validar o cadastro
             await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "⚠️ *Estado (UF) ausente*\n\nNão conseguimos identificar a UF de sua Loja para o cálculo preciso. Atualize seu registro.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]])
            )
             return
             
        await query.answer(f"Calculando raio de {int(raio_km)}km...", show_alert=False)
             
        # 3. Coletar destinos únicos de eventos futuros
        eventos = listar_eventos() or []
        agora = datetime.now()
        eventos_futuros = []
        cidades_com_eventos = []
        
        lojas_map = _lojas_map_cache()
        
        for ev in eventos:
            dt = _data_hora_evento(ev)
            if dt and dt >= agora and _status_evento_normalizado(ev) != "cancelado":
                # Resolve cidade e UF da loja do evento
                l_id = ev.get("ID da loja") or ev.get("loja_id")
                loja_ev = lojas_map.get(l_id) if l_id else None
                
                # Oriente do evento
                ori_ev_raw = str(ev.get("Oriente") or "").strip()
                cid_ev = re.split(r"[-/]", ori_ev_raw)[0].strip()
                
                uf_ev = ""
                if loja_ev:
                    uf_ev = str(loja_ev.get("Estado UF") or loja_ev.get("estado_uf") or "").strip().upper()
                if not uf_ev:
                    m_uf = re.search(r"[-/]\s*([A-Za-z]{2})\b", ori_ev_raw)
                    uf_ev = m_uf.group(1).upper() if m_uf else ""
                    
                if cid_ev and uf_ev:
                    eventos_futuros.append({
                        "evento": ev,
                        "cidade": cid_ev,
                        "uf": uf_ev
                    })
                    cidades_com_eventos.append({
                        "cidade": cid_ev,
                        "uf": uf_ev
                    })
                    
        if not cidades_com_eventos:
             await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "📍 *Sem sessões agendadas*\n\nNão encontramos nenhuma sessão futura com coordenadas válidas para busca.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]])
            )
             return
             
        # 4. Aplicar Filtro de Raio Geográfico
        cidades_filtradas = filtrar_locais_por_raio(cidade_origem, uf_origem, cidades_com_eventos, raio_km=raio_km)
        
        if not cidades_filtradas:
             # Constrói teclado mesmo vazio para permitir alterar raio
             teclado_botoes = [
                 [
                     InlineKeyboardButton("🎯 25km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|25"),
                     InlineKeyboardButton("🎯 50km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|50"),
                 ],
                 [
                     InlineKeyboardButton("🎯 100km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|100"),
                     InlineKeyboardButton("🎯 200km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|200"),
                 ],
                 [InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]
             ]
             
             await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                f"📍 *Nenhuma sessão próxima*\n\nNão encontramos sessões num raio de *{int(raio_km)}km* a partir de *{cidade_origem}-{uf_origem}*.\n\nTente expandir o raio de busca nos botões abaixo:",
                InlineKeyboardMarkup(teclado_botoes)
            )
             return
             
        # Map das menores distâncias por cidade para exibição
        mapa_distancias = {f"{c['cidade'].lower()}-{c['uf'].upper()}": c["distancia_km"] for c in cidades_filtradas}
        
        # 5. Cruzar resultados e montar botões
        botoes_resultado = []
        eventos_filtrados_com_dist = []
        for item_fut in eventos_futuros:
            chave = f"{item_fut['cidade'].lower()}-{item_fut['uf'].upper()}"
            if chave in mapa_distancias:
                ev_dist = dict(item_fut)
                ev_dist["distancia"] = mapa_distancias[chave]
                eventos_filtrados_com_dist.append(ev_dist)
                
        # Ordena por proximidade geográfica e secundariamente cronológico
        eventos_filtrados_com_dist.sort(key=lambda x: (x["distancia"], _data_hora_evento(x["evento"]) or agora))
        
        # Limita quantidade
        eventos_filtrados_com_dist = eventos_filtrados_com_dist[:MAX_EVENTOS_LISTA]
        
        # Agrupa e cria os botões adicionando distância ao texto
        for item in eventos_filtrados_com_dist:
            ev = item["evento"]
            dist = item["distancia"]
            dist_txt = f"{dist:.0f}km" if dist >= 1 else "próximo"
            
            # Linha de texto padrão do evento
            texto_base = _linha_botao_evento(ev)
            # Adiciona a distância no final para o usuário saber quão perto é
            texto_completo = f"{texto_base} ({dist_txt})"
            
            id_evento = normalizar_id_evento(ev)
            botoes_resultado.append([InlineKeyboardButton(
                texto_completo,
                callback_data=f"evento|{_encode_cb(id_evento)}"
            )])
            
        # 6. Adicionar Seletor Rápido de Raio no rodapé
        botoes_resultado.append([
            InlineKeyboardButton("🎯 25km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|25"),
            InlineKeyboardButton("🎯 50km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|50")
        ])
        botoes_resultado.append([
            InlineKeyboardButton("🎯 100km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|100"),
            InlineKeyboardButton("🎯 200km", callback_data=f"data|{TOKEN_GEO_RAIO_MENU}|200")
        ])
        botoes_resultado.append([InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")])
        
        from src.sheets_supabase import registrar_log_busca
        registrar_log_busca(uf=uf_origem, cidade=cidade_origem, encontrou_resultados=True)
        
        await navegar_para(
            update, context,
            f"Ver Sessões > Proximidade ({int(raio_km)}km)",
            f"📍 *Sessões próximas ({int(raio_km)}km):*\nCalculado a partir de *{cidade_origem}-{uf_origem}*.\n\nSelecione uma abaixo ou altere o raio:",
            InlineKeyboardMarkup(botoes_resultado)
        )
        return

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

    if token_or_data == TOKEN_POR_RITO_MENU:
        eventos = listar_eventos() or []
        ritos = _ritos_disponiveis(eventos)
        if not ritos:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "*Sessões por Rito*\n\nAinda não há ritos vinculados às sessões disponíveis.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]])
            )
            return

        botoes = [
            [InlineKeyboardButton(f"📜 {rito}", callback_data=f"rito|{TOKEN_POR_RITO_MENU}|{_encode_cb(rito)}")]
            for rito in ritos[:MAX_EVENTOS_LISTA]
        ]
        botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")])
        await navegar_para(
            update, context,
            "Ver Sessões > Por Rito",
            "📜 *Selecione o rito:*",
            InlineKeyboardMarkup(botoes)
        )
        return

    if token_or_data == TOKEN_POR_LOCALIDADE_MENU:
        eventos = listar_eventos() or []
        lojas_map = _lojas_map_cache()
        ufs = _ufs_ativas_eventos(eventos, lojas_map)
        
        if not ufs:
            ufs_todas = buscar_estados_uf()
            ufs = [u["sigla"] for u in ufs_todas]

        linhas_uf = []
        linha_atual = []
        for uf in ufs:
            linha_atual.append(InlineKeyboardButton(uf, callback_data=f"geo_uf|{uf}"))
            if len(linha_atual) >= 6:
                linhas_uf.append(linha_atual)
                linha_atual = []
        if linha_atual:
            linhas_uf.append(linha_atual)
            
        linhas_uf.append([InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")])
        
        await navegar_para(
            update, context,
            "Ver Sessões > Por Localidade",
            "📍 *Busca por Localidade*\n\nSelecione o estado (UF) desejado:",
            InlineKeyboardMarkup(linhas_uf)
        )
        return

    if token_or_data == TOKEN_POR_POTENCIA_MENU:
        eventos = listar_eventos() or []
        potencias = _potencias_ativas_eventos(eventos)
        
        if not potencias:
             await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "🏛️ *Sessões por Potência*\n\nAinda não há potências vinculadas às sessões disponíveis.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")]])
            )
             return
             
        botoes = []
        for pot in potencias[:MAX_EVENTOS_LISTA]:
            botoes.append([InlineKeyboardButton(f"🏛️ {pot}", callback_data=f"potencia_filtro|{pot}")])
            
        botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")])
        
        await navegar_para(
            update, context,
            "Ver Sessões > Por Potência",
            "🏛️ *Selecione a Potência:*",
            InlineKeyboardMarkup(botoes)
        )
        return

    eventos = listar_eventos() or []

    if token_or_data in (TOKEN_SEMANA_ATUAL, TOKEN_PROXIMA_SEMANA, TOKEN_MES_ATUAL, TOKEN_PROXIMOS_MESES):
        titulo, filtrados = _filtrar_por_periodo(eventos, token_or_data)

        from src.sheets_supabase import registrar_log_busca
        if not filtrados:
            registrar_log_busca(grau=grau, encontrou_resultados=False)
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                f"*{titulo}*\n\nNão há sessões agendadas para este período.",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Voltar", callback_data="ver_eventos")
                ]])
            )
            return

        from src.sheets_supabase import registrar_log_busca
        registrar_log_busca(grau=grau, encontrou_resultados=True)
        from src.sheets_supabase import registrar_log_busca
        registrar_log_busca(rito=rito, encontrou_resultados=True)
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

        from src.sheets_supabase import registrar_log_busca
        if not filtrados:
            registrar_log_busca(rito=rito, encontrou_resultados=False)
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
                _linha_botao_evento(ev, omitir_grau=True),
                callback_data=f"evento|{_encode_cb(id_evento)}"
            )])

        botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_GRAU_MENU}")])

        await navegar_para(
            update, context,
            f"Ver Sessões > Por Grau > {grau}",
            f"*{titulo}*\n\nSelecione uma sessão:",
            InlineKeyboardMarkup(botoes)
        )


async def mostrar_eventos_por_rito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partes = query.data.split("|", 2)
    if len(partes) < 3:
        return

    _, data_or_menu, rito_cod = partes
    rito = _decode_cb(rito_cod)
    eventos = listar_eventos() or []

    if data_or_menu == TOKEN_POR_RITO_MENU:
        titulo, filtrados = _filtrar_por_rito(eventos, rito)

        if not filtrados:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                f"*{titulo}*\n\nNão há sessões para este rito no momento.",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_RITO_MENU}")
                ]])
            )
            return

        filtrados = filtrados[:MAX_EVENTOS_LISTA]
        botoes = []
        for ev in filtrados:
            id_evento = normalizar_id_evento(ev)
            botoes.append([InlineKeyboardButton(
                _linha_botao_evento(ev, omitir_rito=True),
                callback_data=f"evento|{_encode_cb(id_evento)}"
            )])

        botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_RITO_MENU}")])

        await navegar_para(
            update, context,
            f"Ver Sessões > Por Rito > {_normalizar_rito(rito)}",
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
    potencia = formatar_potencia(*potencia_de_dados(evento))
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

    id_evento_cod = partes[1]
    tipo_agape = partes[2]
    bypass_grau = len(partes) >= 4 and partes[3] == "bypass"
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

    if not membro_esta_ativo(membro):
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚠️ *Cadastro em Análise*\n\n"
            "Seu registro está na *Câmara de Reflexão* aguardando a validação do Secretário da Loja.\n"
            "Assim que for aprovado, você receberá uma notificação e poderá confirmar sua presença em sessões.",
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(
                query,
                "Seu cadastro ainda aguarda aprovação do Secretário da Loja.",
                show_alert=True
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
    if not bypass_grau and not _pode_confirmar_presenca(grau_cadastrado, grau_sessao):
        pauta = str(evento.get("Pauta", "") or "").strip()
        texto_aviso = (
            f"Ir.·., a sessão '{pauta}' é de Grau {grau_sessao}, mas seu cadastro consta como {grau_cadastrado}.\n\n"
            f"Verifique seu cadastro com o secretário de sua oficina ou confirme assim mesmo caso seus dados estejam desatualizados. 🐐"
        )
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("👉 Confirmar assim mesmo", callback_data=f"confirmar|{id_evento_cod}|{tipo_agape}|bypass")],
            [InlineKeyboardButton("👤 Ver meu cadastro", callback_data="meu_cadastro")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="fechar_mensagem")],
        ])
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            texto_aviso,
            teclado,
            limpar_conteudo=True
        )
        if update.effective_chat.type in ["group", "supergroup"]:
            await _responder_callback_seguro(query, "Verifique seu privado.", show_alert=True)
        return ConversationHandler.END

    # INTERCEPTAÇÃO LOGÍSTICA REMOVIDA (Clique Único aplicado)
    pass

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

    # Hook Conquistas
    try:
        from src.conquistas import checar_conquistas_presenca
        import asyncio
        asyncio.create_task(checar_conquistas_presenca(user_id, evento, membro, participacao_agape, context.bot))
    except Exception:
        pass

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
    pauta = str(evento.get("Pauta", "") or "").strip()
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
                pauta=pauta,
            )
        else:
            resposta = CONFIRMACAO_SEM_AGAPE_TMPL.format(
                nome=membro.get('Nome', ''),
                data=data,
                loja=nome_loja,
                numero_fmt=numero_fmt,
                horario=horario,
                participacao=texto_participacao,
                pauta=pauta,
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

    if not membro_esta_ativo(membro):
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚠️ *Cadastro em Análise*\n\n"
            "Seu registro está na *Câmara de Reflexão* aguardando a validação do Secretário da Loja.\n"
            "Assim que for aprovado, você poderá confirmar presenças e acessar o painel completo.",
            limpar_conteudo=True
        )
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

    # INTERCEPTAÇÃO LOGÍSTICA: Aviso de Ágape (Hospitalaria Digital)
    if tipo_agape != "sem":
        botoes = [
            [InlineKeyboardButton("✅ Confirmar Fisicamente", callback_data=f"confirmar|{_encode_cb(id_evento)}|{tipo_agape}|final")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="fechar_mensagem")]
        ]
        
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚠️ *Responsabilidade Logística: Confirmação de Ágape*\n\n"
            "Irmão, observe que sua presença no ágape acarreta custos, preparo alimentar "
            "e dimensionamento logístico pela *Hospitalaria* anfitriã.\n\n"
            "Você confirma que estará fisicamente presente e assume este compromisso fraterno? 🐐",
            InlineKeyboardMarkup(botoes),
            limpar_conteudo=True
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

    # Hook Conquistas
    try:
        from src.conquistas import checar_conquistas_presenca
        import asyncio
        asyncio.create_task(checar_conquistas_presenca(user_id, evento, membro, participacao_agape, context.bot))
    except Exception:
        pass

    await notificar_secretario(context, evento, membro, tipo_agape)

    data = str(evento.get("Data do evento", "") or "").strip()
    pauta = str(evento.get("Pauta", "") or "").strip()
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
                                "Número da loja": c.get("Número da loja", c.get("numero_loja", "")),
                                "Oriente": c.get("Oriente", c.get("oriente", "")),
                                "Potência": c.get("Potência", c.get("potencia", "")),
                                "Venerável Mestre": c.get("Venerável Mestre", c.get("veneravel_mestre", "")),
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

    def _clean(val):
        return str(val or "").strip().lower()

    for c in confirmacoes:
        tid = _tid_to_int(c.get("Telegram ID") or c.get("telegram_id"))
        membro = buscar_membro(tid) if tid is not None else None

        # Selo do Cabrito: comparar se o membro é visitante da loja do evento
        es_visitante = False
        if evento:
            ev_loja_id = _clean(evento.get("ID da loja") or evento.get("loja_id"))

            if membro:
                m_loja_id = _clean(membro.get("ID da loja") or membro.get("loja_id"))
                if ev_loja_id and m_loja_id:
                    es_visitante = ev_loja_id != m_loja_id
                else:
                    ev_loja_nome = _clean(evento.get("Nome da loja") or evento.get("nome_loja"))
                    ev_loja_num = _clean(evento.get("Número da loja") or evento.get("numero_loja"))
                    m_loja_nome = _clean(membro.get("Loja") or membro.get("loja"))
                    m_loja_num = _clean(membro.get("Número da loja") or membro.get("numero_loja"))
                    es_visitante = (ev_loja_nome != m_loja_nome) or (ev_loja_num != m_loja_num)
            else:
                ev_loja_nome = _clean(evento.get("Nome da loja") or evento.get("nome_loja"))
                ev_loja_num = _clean(evento.get("Número da loja") or evento.get("numero_loja"))
                c_loja_nome = _clean(c.get("Loja") or c.get("loja"))
                c_loja_num = _clean(c.get("Número da loja") or c.get("numero_loja"))
                es_visitante = (ev_loja_nome != c_loja_nome) or (ev_loja_num != c_loja_num)

        suffix = " 🐐" if es_visitante else ""

        if membro:
            dados = dict(membro)
            dados["Nome"] = (dados.get("Nome") or dados.get("nome") or "").strip() + suffix
            linhas.append(montar_linha_confirmado(dados))
        else:
            snapshot = {
                "Grau": c.get("Grau", c.get("grau", "")),
                "Nome": (c.get("Nome") or c.get("nome") or "").strip() + suffix,
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
    potencia = formatar_potencia(*potencia_de_dados(evento))

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

    endereco = str(evento.get("Endereço da sessão", "") or "").strip()
    if "http://" in endereco.lower() or "https://" in endereco.lower():
        btn_local = InlineKeyboardButton("📍 Localização", url=endereco)
    else:
        btn_local = InlineKeyboardButton("📍 Localização", callback_data=f"ver_local|{_encode_cb(id_evento)}")

    teclado = InlineKeyboardMarkup([
        [btn_local],
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


# ============================================
# AÇÕES DE SELEÇÃO GEOGRÁFICA E POTÊNCIA
# ============================================

async def mostrar_eventos_por_uf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partes = query.data.split("|", 1)
    if len(partes) < 2:
        return
        
    uf = partes[1].upper()
    eventos = listar_eventos() or []
    lojas_map = _lojas_map_cache()
    
    cidades = _cidades_ativas_eventos(eventos, lojas_map, uf)
    
    from src.sheets_supabase import registrar_log_busca
    if not cidades:
        registrar_log_busca(uf=uf, encontrou_resultados=False)
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            f"📍 *Sessões em {uf}*\n\nNão há sessões programadas para cidades deste estado no momento.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_LOCALIDADE_MENU}")]])
        )
        return
        
    from src.sheets_supabase import registrar_log_busca
    registrar_log_busca(uf=uf, encontrou_resultados=True)
    botoes = []
    for cid in cidades[:MAX_EVENTOS_LISTA]:
        botoes.append([InlineKeyboardButton(f"🌆 {cid}", callback_data=f"geo_cid|{uf}|{cid}")])
        
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_LOCALIDADE_MENU}")])
    
    await navegar_para(
        update, context,
        f"Ver Sessões > Localidade > {uf}",
        f"📍 *Cidades em {uf} com sessões agendadas:*\nSelecione uma para ver os detalhes:",
        InlineKeyboardMarkup(botoes)
    )

async def mostrar_eventos_por_cidade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partes = query.data.split("|", 2)
    if len(partes) < 3:
        return
        
    uf = partes[1].upper()
    cidade = partes[2]
    
    eventos = listar_eventos() or []
    lojas_map = _lojas_map_cache()
    
    titulo, filtrados = _filtrar_por_cidade(eventos, lojas_map, uf, cidade)
    
    from src.sheets_supabase import registrar_log_busca
    if not filtrados:
        registrar_log_busca(uf=uf, cidade=cidade, encontrou_resultados=False)
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            f"*{titulo}*\n\nNão há sessões para esta cidade no momento.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data=f"geo_uf|{uf}")]])
        )
        return
        
    from src.sheets_supabase import registrar_log_busca
    registrar_log_busca(uf=uf, cidade=cidade, encontrou_resultados=True)
    filtrados = filtrados[:MAX_EVENTOS_LISTA]
    botoes = []
    for ev in filtrados:
        id_evento = normalizar_id_evento(ev)
        botoes.append([InlineKeyboardButton(
            _linha_botao_evento(ev),
            callback_data=f"evento|{_encode_cb(id_evento)}"
        )])
        
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"geo_uf|{uf}")])
    
    await navegar_para(
        update, context,
        f"Ver Sessões > Localidade > {uf} > {cidade}",
        f"*{titulo}*\n\nSelecione uma sessão:",
        InlineKeyboardMarkup(botoes)
    )

async def mostrar_eventos_por_potencia_filtro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partes = query.data.split("|", 1)
    if len(partes) < 2:
        return
        
    potencia = partes[1]
    eventos = listar_eventos() or []
    
    titulo, filtrados = _filtrar_por_potencia(eventos, potencia)
    
    if not filtrados:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            f"*{titulo}*\n\nNão há sessões para esta potência no momento.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_POTENCIA_MENU}")]])
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
        
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"data|{TOKEN_POR_POTENCIA_MENU}")])
    
    await navegar_para(
        update, context,
        f"Ver Sessões > Potência > {potencia}",
        f"*{titulo}*\n\nSelecione uma sessão:",
        InlineKeyboardMarkup(botoes)
    )


async def ver_localizacao_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envia o endereço da sessão via DM para cópia com um clique, ou exibe alerta se privado indisponível."""
    query = update.callback_query
    if not query:
        return
        
    partes = query.data.split("|", 1)
    if len(partes) < 2:
        await _responder_callback_seguro(query, "Erro ao decodificar requisição.", show_alert=True)
        return
        
    id_evento = _decode_cb(partes[1])
    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    
    if not evento:
        await _responder_callback_seguro(query, "Sessão indisponível para consulta.", show_alert=True)
        return
        
    endereco = str(evento.get("Endereço da sessão", "") or "").strip()
    nome_loja = str(evento.get("Nome da loja", "") or "Loja").strip()
    
    if not endereco:
        await _responder_callback_seguro(query, "Esta sessão não possui endereço configurado.", show_alert=True)
        return
        
    await _responder_callback_seguro(query, "📍 Processando endereço...")
    
    # Formata texto com backticks para cópia ultra-rápida no Telegram
    texto_dm = (
        f"📍 *Localização da Sessão*\n\n"
        f"🏛️ *{nome_loja}*\n\n"
        f"Toque no texto abaixo para copiar o endereço completo:\n\n"
        f"`{endereco}`"
    )
    
    user_id = update.effective_user.id
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=texto_dm,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning("Falha ao enviar DM de endereço para %s: %s", user_id, e)
        # Fallback de pop-up curto se não for possível enviar a DM
        await query.answer(
            text=f"📍 Endereço da Sessão:\n\n{endereco[:150]}",
            show_alert=True
        )
