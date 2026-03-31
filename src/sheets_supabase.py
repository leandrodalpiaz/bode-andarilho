# src/sheets_supabase.py
"""
Substituto do sheets.py usando Supabase como backend.
MantÃ©m as mesmas assinaturas, nomes e retornos do sheets.py original,
para que a migraÃ§Ã£o seja feita apenas trocando o import nos outros arquivos.
"""
from __future__ import annotations

import os
import re
import uuid
import time
import asyncio
import logging
import pathlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from supabase import create_client, Client
from dotenv import load_dotenv

# Garante carregamento do .env a partir da raiz do projeto,
# independente do diretÃ³rio de trabalho atual.
_ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)


# =========================
# Cache para otimizaÃ§Ãµes de performance
# =========================
_cache_membros: Dict[int, tuple] = {}   # telegram_id -> (dados, timestamp)
_ttl_membros = 600                       # 10 minutos
_cache_confirmacoes: Dict[tuple, tuple] = {}  # (id_evento, telegram_id) -> (dados, timestamp)
_ttl_confirmacoes = 300                  # 5 minutos
_cache_eventos: Dict[bool, tuple] = {}   # include_inativos -> (dados, timestamp)
_ttl_eventos = 30                        # 30 segundos
_cache_lojas: Dict[int, tuple] = {}      # telegram_id -> (dados, timestamp)
_ttl_lojas = 300                         # 5 minutos

# Fallback para notificaÃ§Ãµes pendentes do secretÃ¡rio quando a tabela
# dedicada ainda nÃ£o foi criada no Supabase.
_notif_secretario_pendentes_em_memoria: Dict[int, List[Dict[str, str]]] = {}
_notif_secretario_pendentes_tabela_indisponivel = False
_notif_secretario_pendentes_alertado = False


# =========================
# ConfiguraÃ§Ã£o do Supabase
# =========================
_SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

if not _SUPABASE_URL or not _SUPABASE_KEY:
    raise ValueError("VariÃ¡veis de ambiente SUPABASE_URL e SUPABASE_KEY sÃ£o obrigatÃ³rias.")

supabase: Client = create_client(_SUPABASE_URL, _SUPABASE_KEY)

logger = logging.getLogger(__name__)


def _erro_tabela_notif_secretario_pendentes(exc: Exception) -> bool:
    """Detecta erro de tabela ausente para notificaÃ§Ãµes pendentes do secretÃ¡rio."""
    msg = str(exc or "")
    return (
        "notificacoes_secretario_pendentes" in msg
        and ("PGRST205" in msg or "Could not find the table" in msg)
    )


def _marcar_tabela_notif_secretario_pendentes_indisponivel(exc: Exception) -> None:
    """Marca tabela como indisponÃ­vel e registra aviso Ãºnico no log."""
    global _notif_secretario_pendentes_tabela_indisponivel
    global _notif_secretario_pendentes_alertado

    _notif_secretario_pendentes_tabela_indisponivel = True
    if not _notif_secretario_pendentes_alertado:
        logger.warning(
            "Tabela 'notificacoes_secretario_pendentes' indisponÃ­vel no Supabase. "
            "Usando fallback em memÃ³ria atÃ© a tabela ser criada. Erro original: %s",
            exc,
        )
        _notif_secretario_pendentes_alertado = True


def _mem_registrar_notificacao_secretario_pendente(secretario_id: int, item: Dict[str, str]) -> bool:
    sid = _norm_intlike(secretario_id)
    if not sid:
        return False

    lista = _notif_secretario_pendentes_em_memoria.setdefault(sid, [])
    lista.append(
        {
            "id": str(len(lista) + 1),
            "secretario_id": str(sid),
            "nome": _norm_text(item.get("nome")),
            "data": _norm_text(item.get("data")),
            "loja": _norm_text(item.get("loja")),
            "agape": _norm_text(item.get("agape")),
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return True


def _mem_listar_notificacoes_secretario_pendentes(secretario_id: int) -> List[Dict[str, str]]:
    sid = _norm_intlike(secretario_id)
    if not sid:
        return []
    return list(_notif_secretario_pendentes_em_memoria.get(sid, []))


def _mem_listar_secretarios_com_notificacoes_pendentes() -> List[int]:
    return [sid for sid, itens in _notif_secretario_pendentes_em_memoria.items() if itens]


def _mem_remover_notificacoes_secretario_pendentes(secretario_id: int) -> bool:
    sid = _norm_intlike(secretario_id)
    if not sid:
        return False
    _notif_secretario_pendentes_em_memoria.pop(sid, None)
    return True


# =========================
# Mapeamentos de campo (sheets <-> supabase)
# =========================

# sheets_key -> supabase_column
_MEMBROS_SHEETS_TO_DB: Dict[str, str] = {
    "Telegram ID":        "telegram_id",
    "Nome":               "nome",
    "Loja":               "loja",
    "Grau":               "grau",
    "Oriente":            "oriente",
    "PotÃªncia":           "potencia",
    "Data de cadastro":   "data_cadastro",
    "Cargo":              "cargo",
    "Nivel":              "nivel",
    "Data de nascimento": "data_nascimento",
    "NÃºmero da loja":     "numero_loja",
    "VenerÃ¡vel Mestre":   "veneravel_mestre",
    "NotificaÃ§Ãµes":       "notificacoes",
    "Status":             "status",
}
_MEMBROS_DB_TO_SHEETS: Dict[str, str] = {v: k for k, v in _MEMBROS_SHEETS_TO_DB.items()}

_EVENTOS_SHEETS_TO_DB: Dict[str, str] = {
    "ID Evento":                    "id_evento",
    "ID da loja":                   "loja_id",
    "Data do evento":               "data_evento",
    "Dia da semana":                "dia_semana",
    "Hora":                         "hora",
    "Nome da loja":                 "nome_loja",
    "NÃºmero da loja":               "numero_loja",
    "Oriente":                      "oriente",
    "Grau":                         "grau",
    "Tipo de sessÃ£o":               "tipo_sessao",
    "Rito":                         "rito",
    "PotÃªncia":                     "potencia",
    "Traje obrigatÃ³rio":            "traje",
    "Ãgape":                        "agape",
    "ObservaÃ§Ãµes":                  "observacoes",
    "Telegram ID do grupo":         "grupo_telegram_id",
    "Telegram Message ID do grupo": "grupo_mensagem_id",
    "SecretÃ¡rio snapshot (Telegram ID)": "secretario_snapshot_id",
    "SecretÃ¡rio snapshot (Nome)": "secretario_snapshot_nome",
    "Criado por (Telegram ID)": "criado_por_id",
    "Criado por (Nome)": "criado_por_nome",
    "Ãltima ediÃ§Ã£o por (Telegram ID)": "ultima_edicao_por_id",
    "Ãltima ediÃ§Ã£o por (Nome)": "ultima_edicao_por_nome",
    "Telegram ID do secretÃ¡rio":    "secretario_telegram_id",
    "Status":                       "status",
    "EndereÃ§o da sessÃ£o":           "endereco",
    "Cancelado em":                 "cancelado_em",
    "Cancelado por (Telegram ID)":  "cancelado_por_id",
    "Cancelado por (Nome)":         "cancelado_por_nome",
}
_EVENTOS_DB_TO_SHEETS: Dict[str, str] = {v: k for k, v in _EVENTOS_SHEETS_TO_DB.items()}

_CONFIRMACOES_SHEETS_TO_DB: Dict[str, str] = {
    "ID Evento":        "id_evento",
    "Telegram ID":      "telegram_id",
    "Nome":             "nome",
    "Grau":             "grau",
    "Cargo":            "cargo",
    "Loja":             "loja",
    "Oriente":          "oriente",
    "PotÃªncia":         "potencia",
    "Ãgape":            "agape",
    "Data e hora":      "data_hora",
    "NÃºmero da loja":   "numero_loja",
    "VenerÃ¡vel Mestre": "veneravel_mestre",
}
_CONFIRMACOES_DB_TO_SHEETS: Dict[str, str] = {v: k for k, v in _CONFIRMACOES_SHEETS_TO_DB.items()}

_LOJAS_SHEETS_TO_DB: Dict[str, str] = {
    "ID":            "id",
    "Telegram ID":   "telegram_id",
    "Nome da Loja":  "nome_loja",
    "NÃºmero":        "numero",
    "Rito":          "rito",
    "PotÃªncia":      "potencia",
    "EndereÃ§o":      "endereco",
    "Data Cadastro": "data_cadastro",
    "Oriente da Loja": "oriente_loja",
    "Oriente":       "oriente_loja",  # alias
    "Telegram ID do secretÃ¡rio responsÃ¡vel": "secretario_responsavel_id",
    "Nome do secretÃ¡rio responsÃ¡vel": "secretario_responsavel_nome",
    "VÃ­nculo atualizado em": "vinculo_atualizado_em",
    "VÃ­nculo atualizado por (Telegram ID)": "vinculo_atualizado_por_id",
}
_LOJAS_DB_TO_SHEETS: Dict[str, str] = {
    "id":          "ID",
    "telegram_id":  "Telegram ID",
    "nome_loja":    "Nome da Loja",
    "numero":       "NÃºmero",
    "rito":         "Rito",
    "potencia":     "PotÃªncia",
    "endereco":     "EndereÃ§o",
    "data_cadastro": "Data Cadastro",
    "oriente_loja": "Oriente da Loja",
    "secretario_responsavel_id": "Telegram ID do secretÃ¡rio responsÃ¡vel",
    "secretario_responsavel_nome": "Nome do secretÃ¡rio responsÃ¡vel",
    "vinculo_atualizado_em": "VÃ­nculo atualizado em",
    "vinculo_atualizado_por_id": "VÃ­nculo atualizado por (Telegram ID)",
}

_SHEET_NAME_TO_TABLE: Dict[str, str] = {
    "Membros":       "membros",
    "Eventos":       "eventos",
    "ConfirmaÃ§Ãµes":  "confirmacoes",
    "Lojas":         "lojas",
}

_TABLE_TO_MAP: Dict[str, tuple] = {
    "membros":       (_MEMBROS_SHEETS_TO_DB,    _MEMBROS_DB_TO_SHEETS),
    "eventos":       (_EVENTOS_SHEETS_TO_DB,    _EVENTOS_DB_TO_SHEETS),
    "confirmacoes":  (_CONFIRMACOES_SHEETS_TO_DB, _CONFIRMACOES_DB_TO_SHEETS),
    "lojas":         (_LOJAS_SHEETS_TO_DB,      _LOJAS_DB_TO_SHEETS),
}


def _safe_cache_int(value: Any) -> int:
    """Converte para inteiro de forma segura para uso em chaves de cache."""
    try:
        return int(float(_norm_intlike(value)))
    except Exception:
        return 0


# =========================
# Helpers (internos)
# =========================

def _now_str(segundos: bool = True) -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S" if segundos else "%d/%m/%Y %H:%M")


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    v = str(value).strip()
    return "" if (v == "" or v.lower() == "nan") else v


def _norm_intlike(value: Any) -> str:
    """
    Normaliza valores que podem vir como int/float/str ("123", "123.0", 123, 123.0)
    para string "123". Retorna "" para None/vazio.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        v = value.strip()
        if v == "" or v.lower() == "nan":
            return ""
        try:
            fv = float(v)
            if fv.is_integer():
                return str(int(fv))
        except Exception:
            pass
        return v

    try:
        fv = float(value)
        if fv.is_integer():
            return str(int(fv))
        return str(value)
    except Exception:
        return str(value)


def _norm_status(value: Any) -> str:
    """
    Normaliza status para comparaÃ§Ã£o.
    Regra: vazio/None => "ativo" (retrocompatÃ­vel)
    """
    v = _norm_text(value).lower()
    return v if v else "ativo"


def membro_esta_ativo(membro: Optional[Dict[str, Any]]) -> bool:
    """Retorna True quando o cadastro do membro estÃ¡ ativo."""
    if not membro:
        return False
    status = _norm_status(membro.get("Status") or membro.get("status"))
    return status == "ativo"


def gerar_id_evento() -> str:
    """Gera um ID Ãºnico e estÃ¡vel para o evento."""
    return uuid.uuid4().hex  # 32 chars


# =========================
# FunÃ§Ãµes de conversÃ£o (internas)
# =========================

def _row_to_sheets(table: str, row: dict) -> dict:
    """Converte registro do Supabase (snake_case) para o formato sheets (nomes originais)."""
    _, db_to_sheets = _TABLE_TO_MAP[table]
    out: Dict[str, Any] = {}
    for db_col, value in row.items():
        sheets_key = db_to_sheets.get(db_col, db_col)
        out[sheets_key] = "" if value is None else value

    # Para lojas: garantir alias "Oriente" tambÃ©m
    if table == "lojas":
        out["Oriente"] = out.get("Oriente da Loja", "")

    # Garantir que nivel seja sempre string
    if table == "membros":
        nivel = out.get("Nivel")
        out["Nivel"] = _norm_intlike(nivel) or "1"

    return out


def _sheets_to_row(table: str, data: dict) -> dict:
    """Converte dados no formato sheets para o formato Supabase (snake_case)."""
    sheets_to_db, _ = _TABLE_TO_MAP[table]
    out: Dict[str, Any] = {}
    for k, v in data.items():
        db_col = sheets_to_db.get(k)
        if db_col:
            # Normaliza None para string vazia, mas deixa None para o DB se o valor original era None
            out[db_col] = v
    return out


# =========================
# FunÃ§Ãµes para Membros
# =========================

def listar_membros(include_inativos: bool = False) -> List[Dict[str, Any]]:
    """Retorna membros cadastrados; por padrÃ£o, somente cadastros ativos."""
    try:
        # Evita filtrar por coluna `status` no SQL para compatibilidade com bases
        # antigas que ainda nÃ£o possuem essa coluna.
        resp = supabase.table("membros").select("*").execute()
        membros = [_row_to_sheets("membros", row) for row in (resp.data or [])]

        if include_inativos:
            return membros

        filtrados: List[Dict[str, Any]] = []
        for membro in membros:
            status = _norm_status(membro.get("Status") or membro.get("status"))
            if status == "ativo":
                filtrados.append(membro)

        return filtrados
    except Exception as e:
        logger.error("Erro ao listar membros: %s", e)
        return []


def buscar_membro(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Retorna o dicionÃ¡rio com dados do membro. Otimizado com cache."""
    # Verificar cache
    if telegram_id in _cache_membros:
        cached, timestamp = _cache_membros[telegram_id]
        if time.time() - timestamp < _ttl_membros:
            return cached

    try:
        tid = _norm_intlike(telegram_id)
        if not tid:
            return None

        resp = (
            supabase.table("membros")
            .select("*")
            .eq("telegram_id", tid)
            .limit(1)
            .execute()
        )

        if not resp.data:
            _cache_membros[telegram_id] = (None, time.time())
            return None

        membro = _row_to_sheets("membros", resp.data[0])
        _cache_membros[telegram_id] = (membro, time.time())
        return membro

    except Exception as e:
        logger.error("Erro ao buscar membro: %s", e)
        return None


def _coluna_ausente(exc: Exception, coluna: str) -> bool:
    """
    Retorna True quando a exceÃ§Ã£o indica que a coluna `coluna` nÃ£o existe
    na tabela (PostgREST PGRST204 - schema cache miss).
    """
    txt = str(exc)
    return "PGRST204" in txt and coluna in txt


def _extrair_coluna_ausente(exc: Exception) -> str:
    """Extrai o nome da coluna ausente de erros PGRST204."""
    txt = str(exc or "")
    if "PGRST204" not in txt:
        return ""

    # Exemplos conhecidos:
    # - Could not find the 'coluna' column of 'tabela' in the schema cache
    # - ... "column 'coluna' ..."
    m = re.search(r"'([^']+)'\\s+column", txt)
    if m:
        return _norm_text(m.group(1))

    m = re.search(r"column\\s+'([^']+)'", txt)
    if m:
        return _norm_text(m.group(1))

    return ""


def _insert_com_fallback_colunas(table: str, row: Dict[str, Any]) -> None:
    """
    Insere com fallback automático para bases sem colunas novas.
    Remove apenas a coluna ausente reportada pelo PostgREST.
    """
    payload = dict(row)
    tentativas = 0

    while True:
        tentativas += 1
        try:
            supabase.table(table).insert(payload).execute()
            return
        except Exception as e:
            col = _extrair_coluna_ausente(e)
            if not col or col not in payload or tentativas > 10:
                raise
            logger.warning(
                "Coluna '%s' ausente em '%s' durante INSERT; prosseguindo sem este campo.",
                col,
                table,
            )
            payload.pop(col, None)


def _update_com_fallback_colunas(table: str, where_col: str, where_val: str, row: Dict[str, Any]) -> None:
    """
    Atualiza com fallback automático para bases sem colunas novas.
    Remove apenas a coluna ausente reportada pelo PostgREST.
    """
    payload = dict(row)
    tentativas = 0

    while True:
        tentativas += 1
        try:
            if payload:
                supabase.table(table).update(payload).eq(where_col, where_val).execute()
            return
        except Exception as e:
            col = _extrair_coluna_ausente(e)
            if not col or col not in payload or tentativas > 10:
                raise
            logger.warning(
                "Coluna '%s' ausente em '%s' durante UPDATE; prosseguindo sem este campo.",
                col,
                table,
            )
            payload.pop(col, None)


def cadastrar_membro(dados: dict) -> bool:
    """
    Insere novo membro.
    - Se jÃ¡ existir (Telegram ID), atualiza dados mantendo Nivel.
    - Nivel padrÃ£o: "1".
    """
    try:
        telegram_id = _norm_intlike(dados.get("Telegram ID") or dados.get("telegram_id"))
        if not telegram_id:
            return False

        # Se existe: atualiza (preserva Nivel)
        existente = buscar_membro(int(float(telegram_id)))
        if existente is not None:
            dados_revalidacao = dict(dados)
            dados_revalidacao["Status"] = "Ativo"
            return atualizar_membro(int(float(telegram_id)), dados_revalidacao, preservar_nivel=True)

        # Monta registro para inserÃ§Ã£o
        row: Dict[str, Any] = {
            "telegram_id":    telegram_id,
            "nome":           _norm_text(dados.get("Nome") or dados.get("nome")),
            "grau":           _norm_text(dados.get("Grau") or dados.get("grau")),
            "cargo":          _norm_text(dados.get("Cargo") or dados.get("cargo")),
            "loja":           _norm_text(dados.get("Loja") or dados.get("loja")),
            "numero_loja":    _norm_text(dados.get("NÃºmero da loja") or dados.get("numero_loja")),
            "oriente":        _norm_text(dados.get("Oriente") or dados.get("oriente")),
            "potencia":       _norm_text(dados.get("PotÃªncia") or dados.get("potencia")),
            "data_nascimento": _norm_text(
                dados.get("Data de nascimento") or dados.get("data_nasc") or dados.get("nascimento")
            ),
            "veneravel_mestre": _norm_text(
                dados.get("VenerÃ¡vel Mestre") or dados.get("veneravel_mestre") or dados.get("vm")
            ),
            "nivel": _norm_intlike(dados.get("Nivel")) or "1",
            "status": "Ativo",
        }

        try:
            supabase.table("membros").insert(row).execute()
        except Exception as e_ins:
            if _coluna_ausente(e_ins, "status"):
                logger.warning(
                    "Coluna 'status' ausente em 'membros' â€” INSERT sem ela. "
                    "Adicione-a: ALTER TABLE membros ADD COLUMN status TEXT DEFAULT 'Ativo';"
                )
                row.pop("status", None)
                supabase.table("membros").insert(row).execute()
            else:
                raise

        # Invalidar cache
        _cache_membros.pop(int(float(telegram_id)), None)
        return True

    except Exception as e:
        logger.error("Erro ao cadastrar membro: %s", e)
        return False


def atualizar_membro(telegram_id: int, dados_atualizados: dict, preservar_nivel: bool = True) -> bool:
    """
    Atualiza um membro existente pelo Telegram ID.
    - preservar_nivel=True impede sobrescrever Nivel por acidente.
    """
    try:
        tid = _norm_intlike(telegram_id)
        if not tid:
            return False

        # Preservar Nivel lendo do registro atual, se necessÃ¡rio
        if preservar_nivel:
            existente = buscar_membro(int(float(tid)))
            nivel_atual = _norm_intlike(existente.get("Nivel") if existente else None) or "1"
        else:
            nivel_atual = None

        # Construir dict de atualizaÃ§Ã£o aceitando chaves sheets e snake_case
        update: Dict[str, Any] = {}

        _alias_map = {
            "nome":           "Nome",
            "grau":           "Grau",
            "cargo":          "Cargo",
            "loja":           "Loja",
            "numero_loja":    "NÃºmero da loja",
            "oriente":        "Oriente",
            "potencia":       "PotÃªncia",
            "data_nasc":      "Data de nascimento",
            "vm":             "VenerÃ¡vel Mestre",
            "veneravel_mestre": "VenerÃ¡vel Mestre",
            "notificacoes":   "NotificaÃ§Ãµes",
            "status":         "Status",
        }

        for k, v in dados_atualizados.items():
            # Normaliza alias snake_case -> sheets key
            sheets_key = _alias_map.get(k, k)
            db_col = _MEMBROS_SHEETS_TO_DB.get(sheets_key)
            if db_col:
                update[db_col] = _norm_text(v)

        if not update:
            return True  # nada a atualizar

        # Reaplica Nivel atual se preservar_nivel
        if preservar_nivel:
            update["nivel"] = nivel_atual

        try:
            supabase.table("membros").update(update).eq("telegram_id", tid).execute()
        except Exception as e_upd:
            if _coluna_ausente(e_upd, "status"):
                logger.warning(
                    "Coluna 'status' ausente em 'membros' â€” UPDATE sem ela. "
                    "Adicione-a: ALTER TABLE membros ADD COLUMN status TEXT DEFAULT 'Ativo';"
                )
                update.pop("status", None)
                if update:  # sÃ³ executa se ainda houver outros campos
                    supabase.table("membros").update(update).eq("telegram_id", tid).execute()
            else:
                raise

        # Invalidar cache
        _cache_membros.pop(telegram_id, None)
        _cache_membros.pop(int(float(tid)), None)
        return True

    except Exception as e:
        logger.error("Erro ao atualizar membro: %s", e)
        return False


def atualizar_nivel_membro(telegram_id: int, novo_nivel: str) -> bool:
    """Atualiza somente o Nivel (uso admin)."""
    try:
        tid = _norm_intlike(telegram_id)
        if not tid:
            return False

        nivel = _norm_intlike(novo_nivel) or "1"
        supabase.table("membros").update({"nivel": nivel}).eq("telegram_id", tid).execute()

        # Invalidar cache
        _cache_membros.pop(telegram_id, None)
        _cache_membros.pop(int(float(tid)), None)
        return True

    except Exception as e:
        logger.error("Erro ao atualizar nÃ­vel: %s", e)
        return False


def atualizar_status_membro(telegram_id: int, novo_status: str) -> bool:
    """Atualiza o status do cadastro do membro preservando seu nÃ­vel."""
    status = _norm_text(novo_status) or "Ativo"
    return atualizar_membro(telegram_id, {"Status": status}, preservar_nivel=True)


def excluir_membro(telegram_id: int) -> bool:
    """Exclui fisicamente um membro pelo Telegram ID (fallback para bases sem coluna status)."""
    try:
        tid = _norm_intlike(telegram_id)
        if not tid:
            return False

        supabase.table("membros").delete().eq("telegram_id", tid).execute()

        # Invalidar cache
        _cache_membros.pop(telegram_id, None)
        _cache_membros.pop(int(float(tid)), None)
        return True

    except Exception as e:
        logger.error("Erro ao excluir membro: %s", e)
        return False


# =========================
# FunÃ§Ãµes para Eventos
# =========================

def listar_eventos(include_inativos: bool = False) -> List[dict]:
    """
    Lista eventos. Por padrÃ£o retorna apenas status 'ativo' (ou vazio => ativo).
    Filtro case-insensitive pois alguns registros podem ter "ativo" e outros "Ativo".
    """
    cache_key = bool(include_inativos)
    if cache_key in _cache_eventos:
        cached, timestamp = _cache_eventos[cache_key]
        if time.time() - timestamp < _ttl_eventos:
            return cached

    try:
        query = supabase.table("eventos").select("*")

        if not include_inativos:
            # Consulta Ãºnica: ativos + status nulo/vazio (retrocompatÃ­vel)
            query = query.or_("status.ilike.ativo,status.is.null,status.eq.")

        resp = query.execute()
        rows = resp.data or []
        result = [_row_to_sheets("eventos", row) for row in rows]
        _cache_eventos[cache_key] = (result, time.time())
        return result

    except Exception as e:
        logger.error("Erro ao listar eventos: %s", e)
        return []


def cadastrar_evento(evento: dict) -> Optional[str]:
    """
    Insere um novo evento.
    Retorna o ID Evento (str) ou None em caso de erro.
    """
    try:
        id_evento = _norm_text(evento.get("ID Evento") or evento.get("id_evento"))
        if not id_evento:
            id_evento = gerar_id_evento()

        row = _sheets_to_row("eventos", evento)
        row["id_evento"] = id_evento

        # Normalizar valores None para string vazia onde necessÃ¡rio
        for k in list(row.keys()):
            if row[k] is None:
                row[k] = ""

        _insert_com_fallback_colunas("eventos", row)
        _cache_eventos.clear()
        return id_evento

    except Exception as e:
        logger.error("Erro ao cadastrar evento: %s", e)
        return None


def atualizar_evento(indice: int, evento: dict) -> bool:
    """
    Atualiza um evento existente.
    Prioriza busca por id_evento. O parÃ¢metro `indice` Ã© mantido apenas
    por compatibilidade de assinatura.
    """
    try:
        id_evento = _norm_text(evento.get("ID Evento") or evento.get("id_evento"))
        if not id_evento:
            # Fallback: busca por data_evento + nome_loja
            data_ev = _norm_text(evento.get("Data do evento", ""))
            nome_loja = _norm_text(evento.get("Nome da loja", ""))
            if not data_ev or not nome_loja:
                return False

            resp = (
                supabase.table("eventos")
                .select("id_evento")
                .eq("data_evento", data_ev)
                .eq("nome_loja", nome_loja)
                .limit(1)
                .execute()
            )
            if not resp.data:
                return False
            id_evento = resp.data[0]["id_evento"]

        row = _sheets_to_row("eventos", evento)
        row.pop("id_evento", None)  # nÃ£o atualizar a PK

        # Normalizar valores None
        for k in list(row.keys()):
            if row[k] is None:
                row[k] = ""

        _update_com_fallback_colunas("eventos", "id_evento", id_evento, row)
        _cache_eventos.clear()
        return True

    except Exception as e:
        logger.error("Erro ao atualizar evento: %s", e)
        return False


# =========================
# FunÃ§Ãµes para ConfirmaÃ§Ãµes
# =========================

def registrar_confirmacao(dados: dict) -> bool:
    """
    Registra confirmaÃ§Ã£o.
    Evita duplicar confirmaÃ§Ã£o do mesmo Telegram ID para o mesmo ID Evento.
    """
    try:
        id_evento = _norm_text(dados.get("id_evento") or dados.get("ID Evento"))
        telegram_id = _norm_intlike(dados.get("telegram_id") or dados.get("Telegram ID"))

        if not id_evento or not telegram_id:
            return False

        # FORCE: bypass cache para evitar race conditions
        if buscar_confirmacao(id_evento, int(float(telegram_id)), usar_cache=False):
            return False

        row: Dict[str, Any] = {
            "id_evento":        id_evento,
            "telegram_id":      telegram_id,
            "nome":             _norm_text(dados.get("nome") or dados.get("Nome")),
            "grau":             _norm_text(dados.get("grau") or dados.get("Grau")),
            "cargo":            _norm_text(dados.get("cargo") or dados.get("Cargo")),
            "loja":             _norm_text(dados.get("loja") or dados.get("Loja")),
            "numero_loja":      _norm_text(dados.get("numero_loja") or dados.get("NÃºmero da loja")),
            "oriente":          _norm_text(dados.get("oriente") or dados.get("Oriente")),
            "potencia":         _norm_text(dados.get("potencia") or dados.get("PotÃªncia")),
            "agape":            _norm_text(dados.get("agape") or dados.get("Ãgape")),
            "data_hora":        _now_str(segundos=True),
            "veneravel_mestre": _norm_text(
                dados.get("veneravel_mestre") or dados.get("VenerÃ¡vel Mestre") or dados.get("vm")
            ),
        }

        supabase.table("confirmacoes").insert(row).execute()

        # Invalidar cache
        cache_key = (id_evento, int(float(telegram_id)))
        _cache_confirmacoes.pop(cache_key, None)
        return True

    except Exception as e:
        logger.error("Erro ao registrar confirmaÃ§Ã£o: %s", e)
        return False


def buscar_confirmacao(id_evento: str, telegram_id: int, usar_cache: bool = True) -> Optional[dict]:
    """Verifica se um usuÃ¡rio jÃ¡ confirmou em determinado evento. Otimizado com cache."""
    cache_key = (id_evento, telegram_id)

    if usar_cache and cache_key in _cache_confirmacoes:
        cached, timestamp = _cache_confirmacoes[cache_key]
        if time.time() - timestamp < _ttl_confirmacoes:
            return cached

    try:
        tid = _norm_intlike(telegram_id)
        resp = (
            supabase.table("confirmacoes")
            .select("*")
            .eq("id_evento", _norm_text(id_evento))
            .eq("telegram_id", tid)
            .limit(1)
            .execute()
        )

        if not resp.data:
            _cache_confirmacoes[cache_key] = (None, time.time())
            return None

        result = _row_to_sheets("confirmacoes", resp.data[0])
        _cache_confirmacoes[cache_key] = (result, time.time())
        return result

    except Exception as e:
        logger.error("Erro ao buscar confirmaÃ§Ã£o: %s", e)
        return None


def cancelar_confirmacao(id_evento: str, telegram_id: int) -> bool:
    """Remove a confirmaÃ§Ã£o do usuÃ¡rio no evento."""
    try:
        target_evento = _norm_text(id_evento)
        target_id = _norm_intlike(telegram_id)
        if not target_evento or not target_id:
            return False

        supabase.table("confirmacoes").delete().eq("id_evento", target_evento).eq("telegram_id", target_id).execute()

        # Invalidar cache
        cache_key = (id_evento, telegram_id)
        _cache_confirmacoes.pop(cache_key, None)
        return True

    except Exception as e:
        logger.error("Erro ao cancelar confirmaÃ§Ã£o: %s", e)
        return False


def listar_confirmacoes_por_evento(id_evento: str) -> List[dict]:
    """Retorna lista de confirmaÃ§Ãµes para um evento especÃ­fico."""
    try:
        resp = (
            supabase.table("confirmacoes")
            .select("*")
            .eq("id_evento", _norm_text(id_evento))
            .execute()
        )
        return [_row_to_sheets("confirmacoes", row) for row in (resp.data or [])]

    except Exception as e:
        logger.error("Erro ao listar confirmaÃ§Ãµes: %s", e)
        return []


def cancelar_todas_confirmacoes(id_evento: str) -> bool:
    """Remove todas as confirmaÃ§Ãµes de um evento."""
    try:
        target_evento = _norm_text(id_evento)
        if not target_evento:
            return False

        supabase.table("confirmacoes").delete().eq("id_evento", target_evento).execute()

        # Invalidar cache de todas as entradas relacionadas ao evento
        keys_to_remove = [k for k in _cache_confirmacoes if k[0] == id_evento]
        for k in keys_to_remove:
            _cache_confirmacoes.pop(k, None)

        return True

    except Exception as e:
        logger.error("Erro ao cancelar confirmaÃ§Ãµes: %s", e)
        return False


# =========================
# FunÃ§Ãµes para Lojas (prÃ©-cadastro)
# =========================

def _secretario_responsavel_loja_id(loja: Dict[str, Any]) -> str:
    """Resolve o secretÃ¡rio responsÃ¡vel da loja (novo campo com fallback legado)."""
    sid = _norm_intlike(
        loja.get("Telegram ID do secretÃ¡rio responsÃ¡vel")
        or loja.get("secretario_responsavel_id")
        or loja.get("Telegram ID")
    )
    return sid


def _secretario_responsavel_loja_nome(loja: Dict[str, Any]) -> str:
    """Nome do secretÃ¡rio responsÃ¡vel com fallback para vazio."""
    return _norm_text(
        loja.get("Nome do secretÃ¡rio responsÃ¡vel")
        or loja.get("secretario_responsavel_nome")
    )


def listar_secretarios_ativos() -> List[Dict[str, str]]:
    """Lista membros ativos de nÃ­vel 2 para seleÃ§Ã£o de responsabilidade."""
    membros = listar_membros(include_inativos=False)
    out: List[Dict[str, str]] = []

    for m in membros:
        nivel = _norm_intlike(m.get("Nivel"))
        if nivel != "2":
            continue

        tid = _norm_intlike(m.get("Telegram ID"))
        if not tid:
            continue

        out.append(
            {
                "telegram_id": tid,
                "nome": _norm_text(m.get("Nome")) or "Sem nome",
            }
        )

    out.sort(key=lambda x: x["nome"].lower())
    return out


def listar_lojas(telegram_id: int, include_todas: bool = False) -> List[Dict[str, Any]]:
    """
    Retorna lista de lojas.
    - include_todas=False: lojas do secretÃ¡rio responsÃ¡vel informado.
    - include_todas=True: todas as lojas (uso administrativo).
    """
    cache_key = -1 if include_todas else _safe_cache_int(telegram_id)
    if cache_key in _cache_lojas:
        cached, timestamp = _cache_lojas[cache_key]
        if time.time() - timestamp < _ttl_lojas:
            return cached

    try:
        query = supabase.table("lojas").select("*")
        if not include_todas:
            target = _norm_intlike(telegram_id)
            if not target:
                return []
            # MantÃ©m retrocompatibilidade: responsÃ¡vel novo OU telegram_id legado.
            query = query.or_(f"secretario_responsavel_id.eq.{target},telegram_id.eq.{target}")

        resp = query.execute()
        result = [_row_to_sheets("lojas", row) for row in (resp.data or [])]
        _cache_lojas[cache_key] = (result, time.time())
        return result

    except Exception as e:
        logger.error("Erro ao listar lojas: %s", e)
        return []


def listar_lojas_visiveis(user_id: int, nivel: str) -> List[Dict[str, Any]]:
    """Lista lojas visÃ­veis para o usuÃ¡rio conforme perfil."""
    if str(nivel) == "3":
        return listar_lojas(user_id, include_todas=True)
    return listar_lojas(user_id, include_todas=False)


def buscar_loja_por_id(loja_id: Any) -> Optional[Dict[str, Any]]:
    """Busca loja por ID (PK da tabela lojas)."""
    target = _norm_text(loja_id)
    if not target:
        return None
    try:
        resp = supabase.table("lojas").select("*").eq("id", target).limit(1).execute()
        if not resp.data:
            return None
        return _row_to_sheets("lojas", resp.data[0])
    except Exception as e:
        logger.error("Erro ao buscar loja por id=%s: %s", loja_id, e)
        return None


def buscar_loja_por_nome_numero(nome_loja: Any, numero_loja: Any) -> Optional[Dict[str, Any]]:
    """Busca uma loja pelo par (nome, nÃºmero)."""
    nome = _norm_text(nome_loja)
    numero = _norm_text(numero_loja)
    if not nome:
        return None
    try:
        resp = (
            supabase.table("lojas")
            .select("*")
            .eq("nome_loja", nome)
            .eq("numero", numero)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return None
        return _row_to_sheets("lojas", resp.data[0])
    except Exception as e:
        logger.error("Erro ao buscar loja por nome/numero (%s/%s): %s", nome, numero, e)
        return None


def obter_secretario_responsavel_evento(evento: Dict[str, Any]) -> Optional[int]:
    """
    Resolve o secretÃ¡rio responsÃ¡vel do evento com prioridade:
    1) Loja vinculada (ID da loja)
    2) Loja por (nome, nÃºmero)
    3) Campo do prÃ³prio evento (legado)
    """
    loja = None
    loja_id = _norm_text(evento.get("ID da loja") or evento.get("loja_id"))
    if loja_id:
        loja = buscar_loja_por_id(loja_id)

    if not loja:
        loja = buscar_loja_por_nome_numero(
            evento.get("Nome da loja") or evento.get("nome_loja"),
            evento.get("NÃºmero da loja") or evento.get("numero_loja"),
        )

    if loja:
        sid = _secretario_responsavel_loja_id(loja)
        if sid:
            try:
                return int(float(sid))
            except Exception:
                pass

    legado = _norm_intlike(evento.get("Telegram ID do secretÃ¡rio") or evento.get("secretario_telegram_id"))
    if not legado:
        return None
    try:
        return int(float(legado))
    except Exception:
        return None


def usuario_pode_gerenciar_evento(user_id: int, nivel: str, evento: Dict[str, Any]) -> bool:
    """PermissÃ£o unificada para gerenciamento de evento."""
    if str(nivel) == "3":
        return True
    sid = obter_secretario_responsavel_evento(evento)
    return sid is not None and int(sid) == int(user_id)


def cadastrar_loja(telegram_id: int, dados: Dict[str, Any]) -> bool:
    """
    Cadastra uma nova loja.
    O campo legado `telegram_id` passa a representar o responsÃ¡vel da loja.
    """
    try:
        data_cadastro = datetime.now().strftime("%d/%m/%Y %H:%M")

        responsavel_id = _norm_intlike(
            dados.get("secretario_responsavel_id")
            or dados.get("Telegram ID do secretÃ¡rio responsÃ¡vel")
            or telegram_id
        )
        responsavel_nome = _norm_text(
            dados.get("secretario_responsavel_nome")
            or dados.get("Nome do secretÃ¡rio responsÃ¡vel")
        )

        row: Dict[str, Any] = {
            "telegram_id": str(responsavel_id or _norm_intlike(telegram_id)),
            "secretario_responsavel_id": str(responsavel_id or _norm_intlike(telegram_id)),
            "secretario_responsavel_nome": responsavel_nome,
            "vinculo_atualizado_em": datetime.now().isoformat(timespec="seconds"),
            "vinculo_atualizado_por_id": _norm_intlike(
                dados.get("vinculo_atualizado_por_id") or telegram_id
            ),
            "nome_loja": _norm_text(dados.get("nome", "")),
            "numero": _norm_text(dados.get("numero", "")),
            "oriente_loja": _norm_text(dados.get("oriente", "")),
            "rito": _norm_text(dados.get("rito", "")),
            "potencia": _norm_text(dados.get("potencia", "")),
            "endereco": _norm_text(dados.get("endereco", "")),
            "data_cadastro": data_cadastro,
        }

        _insert_com_fallback_colunas("lojas", row)
        _cache_lojas.clear()
        return True

    except Exception as e:
        logger.error("Erro ao cadastrar loja: %s", e)
        return False


def atualizar_secretario_responsavel_loja(
    loja_id: Any,
    secretario_id: Any,
    secretario_nome: str = "",
    atualizado_por_id: Any = "",
) -> bool:
    """Atualiza o secretÃ¡rio responsÃ¡vel da loja."""
    lid = _norm_text(loja_id)
    sid = _norm_intlike(secretario_id)
    if not lid or not sid:
        return False

    payload: Dict[str, Any] = {
        "telegram_id": sid,  # legado
        "secretario_responsavel_id": sid,
        "secretario_responsavel_nome": _norm_text(secretario_nome),
        "vinculo_atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "vinculo_atualizado_por_id": _norm_intlike(atualizado_por_id),
    }

    try:
        _update_com_fallback_colunas("lojas", "id", lid, payload)
        _cache_lojas.clear()
        return True
    except Exception as e:
        logger.error("Erro ao atualizar secretÃ¡rio responsÃ¡vel da loja %s: %s", lid, e)
        return False


def excluir_loja(telegram_id: int, loja: dict) -> bool:
    """
    Exclui uma loja especÃ­fica.
    Prioriza exclusÃ£o por ID; fallback para nome+nÃºmero+rito.
    """
    try:
        row_id = _norm_text(loja.get("ID") or loja.get("id"))
        if row_id:
            supabase.table("lojas").delete().eq("id", row_id).execute()
            _cache_lojas.clear()
            return True

        resp = supabase.table("lojas").select("*").execute()
        rows = resp.data or []

        for row in rows:
            if _norm_text(row.get("nome_loja")) != _norm_text(loja.get("Nome da Loja", "")):
                continue
            if _norm_text(row.get("numero")) != _norm_text(loja.get("NÃºmero", "")):
                continue
            if _norm_text(row.get("rito")) != _norm_text(loja.get("Rito", "")):
                continue
            supabase.table("lojas").delete().eq("id", row.get("id")).execute()
            _cache_lojas.clear()
            return True

        return False

    except Exception as e:
        logger.error("Erro ao excluir loja: %s", e)
        return False


# =========================
# FunÃ§Ãµes para NotificaÃ§Ãµes
# =========================

def get_notificacao_status(telegram_id: int) -> bool:
    """
    Retorna True se o usuÃ¡rio tem notificaÃ§Ãµes ativas (campo "NotificaÃ§Ãµes" = "SIM").
    Retorna False caso contrÃ¡rio.
    """
    try:
        membro = buscar_membro(telegram_id)
        if not membro:
            return False
        notificacao = str(membro.get("NotificaÃ§Ãµes", "") or "").strip().upper()
        return notificacao == "SIM"
    except Exception as e:
        logger.error("Erro ao buscar status de notificaÃ§Ã£o: %s", e)
        return False


def get_preferencia_lembretes(telegram_id: int) -> bool:
    """
    Retorna a preferÃªncia de lembretes do usuÃ¡rio.

    Regras:
    - "NÃƒO" desativa lembretes e alertas privados.
    - "SIM" ativa explicitamente.
    - vazio/ausente mantÃ©m o comportamento legado: ativo por padrÃ£o.
    """
    try:
        membro = buscar_membro(telegram_id)
        if not membro:
            return True
        notificacao = str(membro.get("NotificaÃ§Ãµes", "") or "").strip().upper()
        if notificacao == "NÃƒO":
            return False
        return True
    except Exception as e:
        logger.error("Erro ao buscar preferÃªncia de lembretes: %s", e)
        return True


def set_notificacao_status(telegram_id: int, ativo: bool) -> bool:
    """
    Atualiza o campo "NotificaÃ§Ãµes" para "SIM" (True) ou "NÃƒO" (False).
    Retorna True se sucesso.
    """
    try:
        valor = "SIM" if ativo else "NÃƒO"
        return atualizar_membro(telegram_id, {"NotificaÃ§Ãµes": valor}, preservar_nivel=True)
    except Exception as e:
        logger.error("Erro ao atualizar status de notificaÃ§Ã£o: %s", e)
        return False


# =========================
# NotificaÃ§Ãµes pendentes do secretÃ¡rio (persistÃªncia)
# =========================

def registrar_notificacao_secretario_pendente(secretario_id: int, item: Dict[str, str]) -> bool:
    """Persiste notificaÃ§Ã£o pendente para envio consolidado fora da janela de silÃªncio."""
    if _notif_secretario_pendentes_tabela_indisponivel:
        return _mem_registrar_notificacao_secretario_pendente(secretario_id, item)

    try:
        sid = _norm_intlike(secretario_id)
        if not sid:
            return False

        row = {
            "secretario_id": sid,
            "nome": _norm_text(item.get("nome")),
            "data_sessao": _norm_text(item.get("data")),
            "loja": _norm_text(item.get("loja")),
            "agape": _norm_text(item.get("agape")),
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        }
        supabase.table("notificacoes_secretario_pendentes").insert(row).execute()
        return True
    except Exception as e:
        if _erro_tabela_notif_secretario_pendentes(e):
            _marcar_tabela_notif_secretario_pendentes_indisponivel(e)
            return _mem_registrar_notificacao_secretario_pendente(secretario_id, item)
        logger.error("Erro ao registrar notificaÃ§Ã£o pendente do secretÃ¡rio: %s", e)
        return False


def listar_notificacoes_secretario_pendentes(secretario_id: int) -> List[Dict[str, str]]:
    """Lista notificaÃ§Ãµes pendentes de um secretÃ¡rio, da mais antiga para a mais nova."""
    if _notif_secretario_pendentes_tabela_indisponivel:
        return _mem_listar_notificacoes_secretario_pendentes(secretario_id)

    try:
        sid = _norm_intlike(secretario_id)
        if not sid:
            return []

        resp = (
            supabase.table("notificacoes_secretario_pendentes")
            .select("id,secretario_id,nome,data_sessao,loja,agape,criado_em")
            .eq("secretario_id", sid)
            .order("id")
            .execute()
        )

        out: List[Dict[str, str]] = []
        for row in (resp.data or []):
            out.append(
                {
                    "id": str(row.get("id", "")),
                    "secretario_id": _norm_text(row.get("secretario_id")),
                    "nome": _norm_text(row.get("nome")),
                    "data": _norm_text(row.get("data_sessao")),
                    "loja": _norm_text(row.get("loja")),
                    "agape": _norm_text(row.get("agape")),
                    "criado_em": _norm_text(row.get("criado_em")),
                }
            )
        return out
    except Exception as e:
        if _erro_tabela_notif_secretario_pendentes(e):
            _marcar_tabela_notif_secretario_pendentes_indisponivel(e)
            return _mem_listar_notificacoes_secretario_pendentes(secretario_id)
        logger.error("Erro ao listar notificaÃ§Ãµes pendentes do secretÃ¡rio: %s", e)
        return []


def listar_secretarios_com_notificacoes_pendentes() -> List[int]:
    """Retorna IDs de secretÃ¡rios que possuem notificaÃ§Ãµes pendentes."""
    if _notif_secretario_pendentes_tabela_indisponivel:
        return _mem_listar_secretarios_com_notificacoes_pendentes()

    try:
        resp = supabase.table("notificacoes_secretario_pendentes").select("secretario_id").execute()
        secretarios: List[int] = []
        vistos = set()
        for row in (resp.data or []):
            sid = _safe_cache_int(row.get("secretario_id"))
            if sid and sid not in vistos:
                vistos.add(sid)
                secretarios.append(sid)
        return secretarios
    except Exception as e:
        if _erro_tabela_notif_secretario_pendentes(e):
            _marcar_tabela_notif_secretario_pendentes_indisponivel(e)
            return _mem_listar_secretarios_com_notificacoes_pendentes()
        logger.error("Erro ao listar secretÃ¡rios com notificaÃ§Ãµes pendentes: %s", e)
        return []


def remover_notificacoes_secretario_pendentes(secretario_id: int) -> bool:
    """Remove todas as notificaÃ§Ãµes pendentes de um secretÃ¡rio apÃ³s envio consolidado."""
    if _notif_secretario_pendentes_tabela_indisponivel:
        return _mem_remover_notificacoes_secretario_pendentes(secretario_id)

    try:
        sid = _norm_intlike(secretario_id)
        if not sid:
            return False

        (
            supabase.table("notificacoes_secretario_pendentes")
            .delete()
            .eq("secretario_id", sid)
            .execute()
        )
        return True
    except Exception as e:
        if _erro_tabela_notif_secretario_pendentes(e):
            _marcar_tabela_notif_secretario_pendentes_indisponivel(e)
            return _mem_remover_notificacoes_secretario_pendentes(secretario_id)
        logger.error("Erro ao remover notificaÃ§Ãµes pendentes do secretÃ¡rio: %s", e)
        return False


# =========================
# UtilitÃ¡rios e funÃ§Ãµes assÃ­ncronas
# =========================

def _parse_data_generica(data_str: str) -> Optional[datetime]:
    if not data_str:
        return None

    texto = str(data_str).strip()
    formatos = (
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def get_all_rows(sheet_name: str) -> List[Dict[str, Any]]:
    """
    Retorna todas as linhas da tabela correspondente ao nome da aba.
    Mapeamento: "Membros" -> membros, "Eventos" -> eventos,
                "ConfirmaÃ§Ãµes" -> confirmacoes, "Lojas" -> lojas.
    Dados retornados jÃ¡ no formato sheets (nomes originais das colunas).
    """
    try:
        table = _SHEET_NAME_TO_TABLE.get(sheet_name)
        if not table:
            logger.error("Nome de aba desconhecido: %s", sheet_name)
            return []

        resp = supabase.table(table).select("*").execute()
        return [_row_to_sheets(table, row) for row in (resp.data or [])]

    except Exception as e:
        logger.error("Erro ao buscar linhas da aba %s: %s", sheet_name, e)
        return []


async def buscar_confirmacoes_membro(user_id: int) -> List[Dict[str, Any]]:
    """Busca todas as confirmaÃ§Ãµes do membro pelo Telegram ID."""
    try:
        target = _norm_intlike(user_id)
        if not target:
            return []

        def _fetch():
            resp = (
                supabase.table("confirmacoes")
                .select("*")
                .eq("telegram_id", target)
                .execute()
            )
            return [_row_to_sheets("confirmacoes", row) for row in (resp.data or [])]

        return await asyncio.to_thread(_fetch)

    except Exception as e:
        logger.error("Erro ao buscar confirmaÃ§Ãµes do membro %s: %s", user_id, e)
        return []


async def buscar_eventos_por_secretario(user_id: int) -> List[Dict[str, Any]]:
    """Busca eventos cujo responsÃ¡vel operacional Ã© o secretÃ¡rio informado."""
    try:
        target = _safe_cache_int(user_id)
        if not target:
            return []
        eventos = await asyncio.to_thread(listar_eventos, True)
        return [ev for ev in eventos if obter_secretario_responsavel_evento(ev) == target]

    except Exception as e:
        logger.error("Erro ao buscar eventos do secretÃ¡rio %s: %s", user_id, e)
        return []


async def buscar_confirmacoes_no_periodo(data_inicio_str: str, data_fim_str: str) -> List[Dict[str, Any]]:
    """Busca confirmaÃ§Ãµes no intervalo de datas (inclusive)."""
    try:
        data_inicio = datetime.strptime(data_inicio_str, "%d/%m/%Y")
        data_fim = datetime.strptime(data_fim_str, "%d/%m/%Y")

        def _fetch():
            return get_all_rows("ConfirmaÃ§Ãµes")

        confirmacoes = await asyncio.to_thread(_fetch)
        filtradas = []

        for conf in confirmacoes:
            data_raw = str(conf.get("Data e hora", "")).split(" ")[0]
            data_conf = _parse_data_generica(data_raw)
            if not data_conf:
                continue
            if data_inicio <= data_conf <= data_fim:
                filtradas.append(conf)

        return filtradas

    except Exception as e:
        logger.error("Erro ao buscar confirmaÃ§Ãµes no perÃ­odo %s - %s: %s", data_inicio_str, data_fim_str, e)
        return []


async def buscar_eventos_no_periodo(data_inicio_str: str, data_fim_str: str) -> List[Dict[str, Any]]:
    """Busca eventos no intervalo de datas (inclusive)."""
    try:
        data_inicio = datetime.strptime(data_inicio_str, "%d/%m/%Y")
        data_fim = datetime.strptime(data_fim_str, "%d/%m/%Y")

        def _fetch():
            return get_all_rows("Eventos")

        eventos = await asyncio.to_thread(_fetch)
        filtrados = []

        for evento in eventos:
            data_evento = _parse_data_generica(evento.get("Data do evento", ""))
            if not data_evento:
                continue
            if data_inicio <= data_evento <= data_fim:
                filtrados.append(evento)

        return filtrados

    except Exception as e:
        logger.error("Erro ao buscar eventos no perÃ­odo %s - %s: %s", data_inicio_str, data_fim_str, e)
        return []


