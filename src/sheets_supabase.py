# src/sheets_supabase.py
"""
Substituto do sheets.py usando Supabase como backend.
Mantém as mesmas assinaturas, nomes e retornos do sheets.py original,
para que a migração seja feita apenas trocando o import nos outros arquivos.
"""
from __future__ import annotations

import os
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
# independente do diretório de trabalho atual.
_ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)


# =========================
# Cache para otimizações de performance
# =========================
_cache_membros: Dict[int, tuple] = {}   # telegram_id -> (dados, timestamp)
_ttl_membros = 600                       # 10 minutos
_cache_confirmacoes: Dict[tuple, tuple] = {}  # (id_evento, telegram_id) -> (dados, timestamp)
_ttl_confirmacoes = 300                  # 5 minutos


# =========================
# Configuração do Supabase
# =========================
_SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

if not _SUPABASE_URL or not _SUPABASE_KEY:
    raise ValueError("Variáveis de ambiente SUPABASE_URL e SUPABASE_KEY são obrigatórias.")

supabase: Client = create_client(_SUPABASE_URL, _SUPABASE_KEY)

logger = logging.getLogger(__name__)


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
    "Potência":           "potencia",
    "Data de cadastro":   "data_cadastro",
    "Cargo":              "cargo",
    "Nivel":              "nivel",
    "Data de nascimento": "data_nascimento",
    "Número da loja":     "numero_loja",
    "Venerável Mestre":   "veneravel_mestre",
    "Notificações":       "notificacoes",
}
_MEMBROS_DB_TO_SHEETS: Dict[str, str] = {v: k for k, v in _MEMBROS_SHEETS_TO_DB.items()}

_EVENTOS_SHEETS_TO_DB: Dict[str, str] = {
    "ID Evento":                    "id_evento",
    "Data do evento":               "data_evento",
    "Dia da semana":                "dia_semana",
    "Hora":                         "hora",
    "Nome da loja":                 "nome_loja",
    "Número da loja":               "numero_loja",
    "Oriente":                      "oriente",
    "Grau":                         "grau",
    "Tipo de sessão":               "tipo_sessao",
    "Rito":                         "rito",
    "Potência":                     "potencia",
    "Traje obrigatório":            "traje",
    "Ágape":                        "agape",
    "Observações":                  "observacoes",
    "Telegram ID do grupo":         "grupo_telegram_id",
    "Telegram ID do secretário":    "secretario_telegram_id",
    "Status":                       "status",
    "Endereço da sessão":           "endereco",
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
    "Potência":         "potencia",
    "Ágape":            "agape",
    "Data e hora":      "data_hora",
    "Número da loja":   "numero_loja",
    "Venerável Mestre": "veneravel_mestre",
}
_CONFIRMACOES_DB_TO_SHEETS: Dict[str, str] = {v: k for k, v in _CONFIRMACOES_SHEETS_TO_DB.items()}

_LOJAS_SHEETS_TO_DB: Dict[str, str] = {
    "Telegram ID":   "telegram_id",
    "Nome da Loja":  "nome_loja",
    "Número":        "numero",
    "Rito":          "rito",
    "Potência":      "potencia",
    "Endereço":      "endereco",
    "Data Cadastro": "data_cadastro",
    "Oriente da Loja": "oriente_loja",
    "Oriente":       "oriente_loja",  # alias
}
_LOJAS_DB_TO_SHEETS: Dict[str, str] = {
    "telegram_id":  "Telegram ID",
    "nome_loja":    "Nome da Loja",
    "numero":       "Número",
    "rito":         "Rito",
    "potencia":     "Potência",
    "endereco":     "Endereço",
    "data_cadastro": "Data Cadastro",
    "oriente_loja": "Oriente da Loja",
}

_SHEET_NAME_TO_TABLE: Dict[str, str] = {
    "Membros":       "membros",
    "Eventos":       "eventos",
    "Confirmações":  "confirmacoes",
    "Lojas":         "lojas",
}

_TABLE_TO_MAP: Dict[str, tuple] = {
    "membros":       (_MEMBROS_SHEETS_TO_DB,    _MEMBROS_DB_TO_SHEETS),
    "eventos":       (_EVENTOS_SHEETS_TO_DB,    _EVENTOS_DB_TO_SHEETS),
    "confirmacoes":  (_CONFIRMACOES_SHEETS_TO_DB, _CONFIRMACOES_DB_TO_SHEETS),
    "lojas":         (_LOJAS_SHEETS_TO_DB,      _LOJAS_DB_TO_SHEETS),
}


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
    Normaliza status para comparação.
    Regra: vazio/None => "ativo" (retrocompatível)
    """
    v = _norm_text(value).lower()
    return v if v else "ativo"


def gerar_id_evento() -> str:
    """Gera um ID único e estável para o evento."""
    return uuid.uuid4().hex  # 32 chars


# =========================
# Funções de conversão (internas)
# =========================

def _row_to_sheets(table: str, row: dict) -> dict:
    """Converte registro do Supabase (snake_case) para o formato sheets (nomes originais)."""
    _, db_to_sheets = _TABLE_TO_MAP[table]
    out: Dict[str, Any] = {}
    for db_col, value in row.items():
        sheets_key = db_to_sheets.get(db_col, db_col)
        out[sheets_key] = "" if value is None else value

    # Para lojas: garantir alias "Oriente" também
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
# Funções para Membros
# =========================

def listar_membros() -> List[Dict[str, Any]]:
    """Retorna lista de todos os membros cadastrados."""
    try:
        resp = supabase.table("membros").select("*").execute()
        return [_row_to_sheets("membros", row) for row in (resp.data or [])]
    except Exception as e:
        logger.error("Erro ao listar membros: %s", e)
        return []


def buscar_membro(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Retorna o dicionário com dados do membro. Otimizado com cache."""
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


def cadastrar_membro(dados: dict) -> bool:
    """
    Insere novo membro.
    - Se já existir (Telegram ID), atualiza dados mantendo Nivel.
    - Nivel padrão: "1".
    """
    try:
        telegram_id = _norm_intlike(dados.get("Telegram ID") or dados.get("telegram_id"))
        if not telegram_id:
            return False

        # Se existe: atualiza (preserva Nivel)
        existente = buscar_membro(int(float(telegram_id)))
        if existente is not None:
            return atualizar_membro(int(float(telegram_id)), dados, preservar_nivel=True)

        # Monta registro para inserção
        row: Dict[str, Any] = {
            "telegram_id":    telegram_id,
            "nome":           _norm_text(dados.get("Nome") or dados.get("nome")),
            "grau":           _norm_text(dados.get("Grau") or dados.get("grau")),
            "cargo":          _norm_text(dados.get("Cargo") or dados.get("cargo")),
            "loja":           _norm_text(dados.get("Loja") or dados.get("loja")),
            "numero_loja":    _norm_text(dados.get("Número da loja") or dados.get("numero_loja")),
            "oriente":        _norm_text(dados.get("Oriente") or dados.get("oriente")),
            "potencia":       _norm_text(dados.get("Potência") or dados.get("potencia")),
            "data_nascimento": _norm_text(
                dados.get("Data de nascimento") or dados.get("data_nasc") or dados.get("nascimento")
            ),
            "veneravel_mestre": _norm_text(
                dados.get("Venerável Mestre") or dados.get("veneravel_mestre") or dados.get("vm")
            ),
            "nivel": _norm_intlike(dados.get("Nivel")) or "1",
        }

        supabase.table("membros").insert(row).execute()

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

        # Preservar Nivel lendo do registro atual, se necessário
        if preservar_nivel:
            existente = buscar_membro(int(float(tid)))
            nivel_atual = _norm_intlike(existente.get("Nivel") if existente else None) or "1"
        else:
            nivel_atual = None

        # Construir dict de atualização aceitando chaves sheets e snake_case
        update: Dict[str, Any] = {}

        _alias_map = {
            "nome":           "Nome",
            "grau":           "Grau",
            "cargo":          "Cargo",
            "loja":           "Loja",
            "numero_loja":    "Número da loja",
            "oriente":        "Oriente",
            "potencia":       "Potência",
            "data_nasc":      "Data de nascimento",
            "vm":             "Venerável Mestre",
            "veneravel_mestre": "Venerável Mestre",
            "notificacoes":   "Notificações",
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

        supabase.table("membros").update(update).eq("telegram_id", tid).execute()

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
        logger.error("Erro ao atualizar nível: %s", e)
        return False


# =========================
# Funções para Eventos
# =========================

def listar_eventos(include_inativos: bool = False) -> List[dict]:
    """
    Lista eventos. Por padrão retorna apenas status 'ativo' (ou vazio => ativo).
    Filtro case-insensitive pois alguns registros podem ter "ativo" e outros "Ativo".
    """
    try:
        query = supabase.table("eventos").select("*")

        if not include_inativos:
            # ilike para comparação case-insensitive
            query = query.ilike("status", "ativo")

        resp = query.execute()
        rows = resp.data or []

        if not include_inativos:
            # Incluir também registros com status NULL/vazio (retrocompatível)
            resp_null = (
                supabase.table("eventos")
                .select("*")
                .is_("status", "null")
                .execute()
            )
            rows += resp_null.data or []

        return [_row_to_sheets("eventos", row) for row in rows]

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

        # Normalizar valores None para string vazia onde necessário
        for k in list(row.keys()):
            if row[k] is None:
                row[k] = ""

        supabase.table("eventos").insert(row).execute()
        return id_evento

    except Exception as e:
        logger.error("Erro ao cadastrar evento: %s", e)
        return None


def atualizar_evento(indice: int, evento: dict) -> bool:
    """
    Atualiza um evento existente.
    Prioriza busca por id_evento. O parâmetro `indice` é mantido apenas
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
        row.pop("id_evento", None)  # não atualizar a PK

        # Normalizar valores None
        for k in list(row.keys()):
            if row[k] is None:
                row[k] = ""

        supabase.table("eventos").update(row).eq("id_evento", id_evento).execute()
        return True

    except Exception as e:
        logger.error("Erro ao atualizar evento: %s", e)
        return False


# =========================
# Funções para Confirmações
# =========================

def registrar_confirmacao(dados: dict) -> bool:
    """
    Registra confirmação.
    Evita duplicar confirmação do mesmo Telegram ID para o mesmo ID Evento.
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
            "numero_loja":      _norm_text(dados.get("numero_loja") or dados.get("Número da loja")),
            "oriente":          _norm_text(dados.get("oriente") or dados.get("Oriente")),
            "potencia":         _norm_text(dados.get("potencia") or dados.get("Potência")),
            "agape":            _norm_text(dados.get("agape") or dados.get("Ágape")),
            "data_hora":        _now_str(segundos=True),
            "veneravel_mestre": _norm_text(
                dados.get("veneravel_mestre") or dados.get("Venerável Mestre") or dados.get("vm")
            ),
        }

        supabase.table("confirmacoes").insert(row).execute()

        # Invalidar cache
        cache_key = (id_evento, int(float(telegram_id)))
        _cache_confirmacoes.pop(cache_key, None)
        return True

    except Exception as e:
        logger.error("Erro ao registrar confirmação: %s", e)
        return False


def buscar_confirmacao(id_evento: str, telegram_id: int, usar_cache: bool = True) -> Optional[dict]:
    """Verifica se um usuário já confirmou em determinado evento. Otimizado com cache."""
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
        logger.error("Erro ao buscar confirmação: %s", e)
        return None


def cancelar_confirmacao(id_evento: str, telegram_id: int) -> bool:
    """Remove a confirmação do usuário no evento."""
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
        logger.error("Erro ao cancelar confirmação: %s", e)
        return False


def listar_confirmacoes_por_evento(id_evento: str) -> List[dict]:
    """Retorna lista de confirmações para um evento específico."""
    try:
        resp = (
            supabase.table("confirmacoes")
            .select("*")
            .eq("id_evento", _norm_text(id_evento))
            .execute()
        )
        return [_row_to_sheets("confirmacoes", row) for row in (resp.data or [])]

    except Exception as e:
        logger.error("Erro ao listar confirmações: %s", e)
        return []


def cancelar_todas_confirmacoes(id_evento: str) -> bool:
    """Remove todas as confirmações de um evento."""
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
        logger.error("Erro ao cancelar confirmações: %s", e)
        return False


# =========================
# Funções para Lojas (pré-cadastro)
# =========================

def listar_lojas(telegram_id: int) -> List[Dict[str, Any]]:
    """Retorna lista de lojas cadastradas por um secretário."""
    try:
        resp = (
            supabase.table("lojas")
            .select("*")
            .eq("telegram_id", str(telegram_id))
            .execute()
        )
        return [_row_to_sheets("lojas", row) for row in (resp.data or [])]

    except Exception as e:
        logger.error("Erro ao listar lojas: %s", e)
        return []


def cadastrar_loja(telegram_id: int, dados: Dict[str, Any]) -> bool:
    """Cadastra uma nova loja para o secretário."""
    try:
        data_cadastro = datetime.now().strftime("%d/%m/%Y %H:%M")

        row: Dict[str, Any] = {
            "telegram_id":  str(telegram_id),
            "nome_loja":    _norm_text(dados.get("nome", "")),
            "numero":       _norm_text(dados.get("numero", "")),
            "oriente_loja": _norm_text(dados.get("oriente", "")),
            "rito":         _norm_text(dados.get("rito", "")),
            "potencia":     _norm_text(dados.get("potencia", "")),
            "endereco":     _norm_text(dados.get("endereco", "")),
            "data_cadastro": data_cadastro,
        }

        supabase.table("lojas").insert(row).execute()
        return True

    except Exception as e:
        logger.error("Erro ao cadastrar loja: %s", e)
        return False


def excluir_loja(telegram_id: int, loja: dict) -> bool:
    """
    Exclui uma loja específica com base nos dados fornecidos.
    Usa combinação de telegram_id + nome_loja + numero + rito para identificar
    a linha correta, igual ao sheets.py.
    """
    try:
        resp = (
            supabase.table("lojas")
            .select("*")
            .eq("telegram_id", str(telegram_id))
            .execute()
        )
        rows = resp.data or []

        for row in rows:
            # Compara Nome da Loja
            if _norm_text(row.get("nome_loja")) != _norm_text(loja.get("Nome da Loja", "")):
                continue

            # Compara Número
            if _norm_text(row.get("numero")) != _norm_text(loja.get("Número", "")):
                continue

            # Compara Rito
            if _norm_text(row.get("rito")) != _norm_text(loja.get("Rito", "")):
                continue

            # Encontrou — apaga pelo id BIGSERIAL
            row_id = row.get("id")
            supabase.table("lojas").delete().eq("id", row_id).execute()
            return True

        return False

    except Exception as e:
        logger.error("Erro ao excluir loja: %s", e)
        return False


# =========================
# Funções para Notificações
# =========================

def get_notificacao_status(telegram_id: int) -> bool:
    """
    Retorna True se o usuário tem notificações ativas (campo "Notificações" = "SIM").
    Retorna False caso contrário.
    """
    try:
        membro = buscar_membro(telegram_id)
        if not membro:
            return False
        notificacao = str(membro.get("Notificações", "") or "").strip().upper()
        return notificacao == "SIM"
    except Exception as e:
        logger.error("Erro ao buscar status de notificação: %s", e)
        return False


def set_notificacao_status(telegram_id: int, ativo: bool) -> bool:
    """
    Atualiza o campo "Notificações" para "SIM" (True) ou "NÃO" (False).
    Retorna True se sucesso.
    """
    try:
        valor = "SIM" if ativo else "NÃO"
        return atualizar_membro(telegram_id, {"Notificações": valor}, preservar_nivel=True)
    except Exception as e:
        logger.error("Erro ao atualizar status de notificação: %s", e)
        return False


# =========================
# Utilitários e funções assíncronas
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
                "Confirmações" -> confirmacoes, "Lojas" -> lojas.
    Dados retornados já no formato sheets (nomes originais das colunas).
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
    """Busca todas as confirmações do membro pelo Telegram ID."""
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
        logger.error("Erro ao buscar confirmações do membro %s: %s", user_id, e)
        return []


async def buscar_eventos_por_secretario(user_id: int) -> List[Dict[str, Any]]:
    """Busca eventos cadastrados por um secretário/admin."""
    try:
        target = _norm_intlike(user_id)
        if not target:
            return []

        def _fetch():
            resp = (
                supabase.table("eventos")
                .select("*")
                .eq("secretario_telegram_id", target)
                .execute()
            )
            return [_row_to_sheets("eventos", row) for row in (resp.data or [])]

        return await asyncio.to_thread(_fetch)

    except Exception as e:
        logger.error("Erro ao buscar eventos do secretário %s: %s", user_id, e)
        return []


async def buscar_confirmacoes_no_periodo(data_inicio_str: str, data_fim_str: str) -> List[Dict[str, Any]]:
    """Busca confirmações no intervalo de datas (inclusive)."""
    try:
        data_inicio = datetime.strptime(data_inicio_str, "%d/%m/%Y")
        data_fim = datetime.strptime(data_fim_str, "%d/%m/%Y")

        def _fetch():
            return get_all_rows("Confirmações")

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
        logger.error("Erro ao buscar confirmações no período %s - %s: %s", data_inicio_str, data_fim_str, e)
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
        logger.error("Erro ao buscar eventos no período %s - %s: %s", data_inicio_str, data_fim_str, e)
        return []
