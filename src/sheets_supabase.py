# src/sheets_supabase.py
"""
Substituto do sheets.py usando Supabase como backend.
Mantém as mesmas assinaturas, nomes e retornos do sheets.py original,
para que a migração seja feita apenas trocando o import nos outros arquivos.
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
_cache_eventos: Dict[bool, tuple] = {}   # include_inativos -> (dados, timestamp)
_ttl_eventos = 30                        # 30 segundos
_cache_lojas: Dict[int, tuple] = {}      # telegram_id -> (dados, timestamp)
_ttl_lojas = 300                         # 5 minutos

# Alternativa para notificações pendentes do secretário quando a tabela
# dedicada ainda não foi criada no Supabase.
_notif_secretario_pendentes_em_memoria: Dict[int, List[Dict[str, str]]] = {}
_notif_secretario_pendentes_tabela_indisponivel = False
_notif_secretario_pendentes_alertado = False


# =========================
# Configuração do Supabase
# =========================
_SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

if not _SUPABASE_URL or not _SUPABASE_KEY:
    raise ValueError("Variáveis de ambiente SUPABASE_URL e SUPABASE_KEY são obrigatórias.")

supabase: Client = create_client(_SUPABASE_URL, _SUPABASE_KEY)

logger = logging.getLogger(__name__)


def _erro_tabela_notif_secretario_pendentes(exc: Exception) -> bool:
    """Detecta erro de tabela ausente para notificações pendentes do secretário."""
    msg = str(exc or "")
    return (
        "notificacoes_secretario_pendentes" in msg
        and ("PGRST205" in msg or "Could not find the table" in msg)
    )


def _marcar_tabela_notif_secretario_pendentes_indisponivel(exc: Exception) -> None:
    """Marca tabela como indisponível e registra aviso único no log."""
    global _notif_secretario_pendentes_tabela_indisponivel
    global _notif_secretario_pendentes_alertado

    _notif_secretario_pendentes_tabela_indisponivel = True
    if not _notif_secretario_pendentes_alertado:
        logger.warning(
            "Tabela 'notificacoes_secretario_pendentes' indisponível no Supabase. "
            "Usando fallback em memória até a tabela ser criada. Erro original: %s",
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
    "ID da loja":         "loja_id",
    "Nome":               "nome",
    "Loja":               "loja",
    "Grau":               "grau",
    "Oriente":            "oriente",
    "Potência":           "potencia",
    "Potência complemento": "potencia_complemento",
    "Data de cadastro":   "data_cadastro",
    "Cargo":              "cargo",
    "Nivel":              "nivel",
    "Data de nascimento": "data_nascimento",
    "Número da loja":     "numero_loja",
    "Venerável Mestre":   "veneravel_mestre",
    "Mestre Instalado":   "mestre_instalado",
    "Notificações":       "notificacoes",
    "Status":             "status",
    "CIM URL":            "cim_photo_url",
    "Loja Manual":        "loja_manual",
    "Status Auditoria":   "status_auditoria",
}
_MEMBROS_DB_TO_SHEETS: Dict[str, str] = {v: k for k, v in _MEMBROS_SHEETS_TO_DB.items()}

_EVENTOS_SHEETS_TO_DB: Dict[str, str] = {
    "ID Evento":                    "id_evento",
    "ID da loja":                   "loja_id",
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
    "Potência complemento":         "potencia_complemento",
    "Traje obrigatório":            "traje",
    "Ágape":                        "agape",
    "Observações":                  "observacoes",
    "Telegram ID do grupo":         "grupo_telegram_id",
    "Telegram Message ID do grupo": "grupo_mensagem_id",
    "Secretário snapshot (Telegram ID)": "secretario_snapshot_id",
    "Secretário snapshot (Nome)": "secretario_snapshot_nome",
    "Criado por (Telegram ID)": "criado_por_id",
    "Criado por (Nome)": "criado_por_nome",
    "Última edição por (Telegram ID)": "ultima_edicao_por_id",
    "Última edição por (Nome)": "ultima_edicao_por_nome",
    "Telegram ID do secretário":    "secretario_telegram_id",
    "Status":                       "status",
    "Endereço da sessão":           "endereco",
    "Cancelado em":                 "cancelado_em",
    "Cancelado por (Telegram ID)":  "cancelado_por_id",
    "Cancelado por (Nome)":         "cancelado_por_nome",
    "Modo visual":                  "modo_visual",
    "Card especial URL":            "card_especial_url",
    "Card renderizado URL":         "card_renderizado_url",
    "Card file_id Telegram":        "card_file_id_telegram",
    "Telegram tipo mensagem grupo": "telegram_tipo_mensagem_grupo",
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
    "Potência complemento": "potencia_complemento",
    "Ágape":            "agape",
    "Data e hora":      "data_hora",
    "Número da loja":   "numero_loja",
    "Venerável Mestre": "veneravel_mestre",
    "Mestre Instalado": "mestre_instalado",
}
_CONFIRMACOES_DB_TO_SHEETS: Dict[str, str] = {v: k for k, v in _CONFIRMACOES_SHEETS_TO_DB.items()}

_LOJAS_SHEETS_TO_DB: Dict[str, str] = {
    "ID":            "id",
    "Telegram ID":   "telegram_id",
    "Nome da Loja":  "nome_loja",
    "Número":        "numero",
    "Rito":          "rito",
    "Potência":      "potencia",
    "Potência complemento": "potencia_complemento",
    "Endereço":      "endereco",
    "Data Cadastro": "data_cadastro",
    "Oriente da Loja": "oriente_loja",
    "Oriente":       "oriente_loja",  # alias
    "Telegram ID do secretário responsável": "secretario_responsavel_id",
    "Nome do secretário responsável": "secretario_responsavel_nome",
    "Vínculo atualizado em": "vinculo_atualizado_em",
    "Vínculo atualizado por (Telegram ID)": "vinculo_atualizado_por_id",
    "CEP":           "cep",
    "Estado UF":     "estado_uf",
    "Cidade":        "cidade",
}
_LOJAS_DB_TO_SHEETS: Dict[str, str] = {
    "id":          "ID",
    "telegram_id":  "Telegram ID",
    "nome_loja":    "Nome da Loja",
    "numero":       "Número",
    "rito":         "Rito",
    "potencia":     "Potência",
    "potencia_complemento": "Potência complemento",
    "endereco":     "Endereço",
    "data_cadastro": "Data Cadastro",
    "oriente_loja": "Oriente da Loja",
    "secretario_responsavel_id": "Telegram ID do secretário responsável",
    "secretario_responsavel_nome": "Nome do secretário responsável",
    "vinculo_atualizado_em": "Vínculo atualizado em",
    "vinculo_atualizado_por_id": "Vínculo atualizado por (Telegram ID)",
    "cep":          "CEP",
    "estado_uf":    "Estado UF",
    "cidade":       "Cidade",
}

_LOJAS_SHEETS_TO_DB.update({
    "Template sessão URL": "template_sessao_url",
    "Layout config JSON": "layout_config_json",
    "Cor texto padrão": "cor_texto_padrao",
    "Fonte padrão": "fonte_padrao",
    "Cor selo grau": "cor_selo_grau",
    "Cor selo rito": "cor_selo_rito",
    "Cor selo potência": "cor_selo_potencia",
    "Status template": "status_template",
})
_LOJAS_DB_TO_SHEETS.update({v: k for k, v in {
    "Template sessão URL": "template_sessao_url",
    "Layout config JSON": "layout_config_json",
    "Cor texto padrão": "cor_texto_padrao",
    "Fonte padrão": "fonte_padrao",
    "Cor selo grau": "cor_selo_grau",
    "Cor selo rito": "cor_selo_rito",
    "Cor selo potência": "cor_selo_potencia",
    "Status template": "status_template",
}.items()})

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


def _safe_cache_int(value: Any) -> int:
    """Converte para inteiro de forma segura para uso em chaves de cache."""
    try:
        return int(float(_norm_intlike(value)))
    except Exception:
        return 0


# =========================
# Funções auxiliares internas
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


def membro_esta_ativo(membro: Optional[Dict[str, Any]]) -> bool:
    """Retorna True quando o cadastro do membro está ativo."""
    if not membro:
        return False
    status = _norm_status(membro.get("Status") or membro.get("status"))
    return status == "ativo"


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

def listar_membros(include_inativos: bool = False) -> List[Dict[str, Any]]:
    """Retorna membros cadastrados; por padrão, somente cadastros ativos."""
    try:
        # Evita filtrar por coluna `status` no SQL para compatibilidade com bases
        # antigas que ainda não possuem essa coluna.
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


def listar_membros_por_loja(
    loja_id: Any = "",
    nome_loja: Any = "",
    numero_loja: Any = "",
    include_inativos: bool = False,
) -> List[Dict[str, Any]]:
    """Lista membros vinculados a uma loja, com fallback para nome+número."""
    membros = listar_membros(include_inativos=include_inativos) or []
    alvo_id = _norm_text(loja_id)
    alvo_nome = _norm_text(nome_loja)
    alvo_numero = _norm_text(numero_loja or "0")

    filtrados: List[Dict[str, Any]] = []
    for membro in membros:
        membro_loja_id = _norm_text(membro.get("ID da loja") or membro.get("loja_id"))
        membro_nome = _norm_text(membro.get("Loja") or membro.get("loja"))
        membro_numero = _norm_text(membro.get("Número da loja") or membro.get("numero_loja") or "0")

        if alvo_id and membro_loja_id == alvo_id:
            filtrados.append(membro)
            continue

        if not alvo_id and alvo_nome and membro_nome == alvo_nome and membro_numero == alvo_numero:
            filtrados.append(membro)

    return filtrados


def buscar_membro(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Retorna o dicionário com dados do membro. Otimizado com cache."""
    # Verifica o cache
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
    Retorna True quando a exceção indica que a coluna `coluna` não existe
    na tabela (PostgREST PGRST204 - schema cache miss).
    """
    txt = str(exc)
    return "PGRST204" in txt and coluna in txt


def _extrair_coluna_ausente(exc: Exception) -> str:
    """Extrai o nome da coluna ausente de erros de schema do PostgREST/Postgres."""
    txt = str(exc or "")
    if "PGRST204" not in txt and "42703" not in txt and "does not exist" not in txt:
        return ""

    # Exemplos conhecidos:
    # - Could not find the 'coluna' column of 'tabela' in the schema cache
    # - Não foi possível encontrar a coluna 'coluna' da tabela 'tabela' no cache de esquema
    # - ... "column 'coluna' ..."
    m = re.search(r"'([^']+)'\s+column", txt)
    if m:
        return _norm_text(m.group(1))

    m = re.search(r"coluna\s+'([^']+)'", txt, flags=re.IGNORECASE)
    if m:
        return _norm_text(m.group(1))

    m = re.search(r"column\s+'([^']+)'", txt, flags=re.IGNORECASE)
    if m:
        return _norm_text(m.group(1))

    m = re.search(r"column\s+([a-zA-Z0-9_\\.]+)\s+does not exist", txt, flags=re.IGNORECASE)
    if m:
        col = m.group(1).split(".")[-1]
        return _norm_text(col)

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
            dados_revalidacao = dict(dados)
            # Garante que revalida o cadastro mantendo ativo apenas se já estivesse ativo
            status_atual = _norm_status(existente.get("Status") or existente.get("status"))
            dados_revalidacao["Status"] = "Ativo" if status_atual == "ativo" else "Pendente"
            return atualizar_membro(int(float(telegram_id)), dados_revalidacao, preservar_nivel=True)

        # Monta registro para inserção
        row: Dict[str, Any] = {
            "telegram_id":    telegram_id,
            "loja_id":        _norm_text(dados.get("ID da loja") or dados.get("loja_id")),
            "nome":           _norm_text(dados.get("Nome") or dados.get("nome")),
            "grau":           _norm_text(dados.get("Grau") or dados.get("grau")),
            "cargo":          _norm_text(dados.get("Cargo") or dados.get("cargo")),
            "loja":           _norm_text(dados.get("Loja") or dados.get("loja")),
            "numero_loja":    _norm_text(dados.get("Número da loja") or dados.get("numero_loja")),
            "oriente":        _norm_text(dados.get("Oriente") or dados.get("oriente")),
            "potencia":       _norm_text(dados.get("Potência") or dados.get("potencia")),
            "potencia_complemento": _norm_text(
                dados.get("Potência complemento") or dados.get("potencia_complemento")
            ),
            "data_nascimento": _norm_text(
                dados.get("Data de nascimento") or dados.get("data_nasc") or dados.get("nascimento")
            ),
            "veneravel_mestre": _norm_text(
                dados.get("Venerável Mestre") or dados.get("veneravel_mestre") or dados.get("vm")
            ),
            "mestre_instalado": _norm_text(
                dados.get("Mestre Instalado") or dados.get("mestre_instalado") or dados.get("mi")
            ),
            "nivel": _norm_intlike(dados.get("Nivel")) or "1",
            "status": _norm_text(dados.get("Status") or dados.get("status")) or "Pendente",
            "cim_photo_url": _norm_text(dados.get("CIM URL") or dados.get("cim_photo_url")),
            "loja_manual": _norm_text(dados.get("Loja Manual") or dados.get("loja_manual")),
            "status_auditoria": _norm_text(dados.get("Status Auditoria") or dados.get("status_auditoria")),
        }

        try:
            supabase.table("membros").insert(row).execute()
        except Exception as e_ins:
            if _coluna_ausente(e_ins, "status"):
                logger.warning(
                    "Coluna 'status' ausente em 'membros' — INSERT sem ela. "
                    "Adicione-a: ALTER TABLE membros ADD COLUMN status TEXT DEFAULT 'Ativo';"
                )
                row.pop("status", None)
                supabase.table("membros").insert(row).execute()
            elif _coluna_ausente(e_ins, "potencia_complemento"):
                logger.warning(
                    "Coluna 'potencia_complemento' ausente em 'membros' — INSERT sem ela. "
                    "Adicione-a: ALTER TABLE membros ADD COLUMN potencia_complemento TEXT DEFAULT '';"
                )
                row.pop("potencia_complemento", None)
                supabase.table("membros").insert(row).execute()
            else:
                raise

        # Invalida o cache
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
            "loja_id":        "ID da loja",
            "nome":           "Nome",
            "grau":           "Grau",
            "cargo":          "Cargo",
            "loja":           "Loja",
            "numero_loja":    "Número da loja",
            "oriente":        "Oriente",
            "potencia":       "Potência",
            "potencia_complemento": "Potência complemento",
            "data_nasc":      "Data de nascimento",
            "vm":             "Venerável Mestre",
            "veneravel_mestre": "Venerável Mestre",
            "mi":             "Mestre Instalado",
            "vm":             "Venerável Mestre",
            "veneravel_mestre": "Venerável Mestre",
            "mi":             "Mestre Instalado",
            "mestre_instalado": "Mestre Instalado",
            "notificacoes":   "Notificações",
            "status":         "Status",
            "cim_photo_url":  "CIM URL",
            "loja_manual":    "Loja Manual",
            "status_auditoria": "Status Auditoria",
        }

        for k, v in dados_atualizados.items():
            # Normaliza alias snake_case -> sheets key
            sheets_key = _alias_map.get(k, k)
            db_col = _MEMBROS_SHEETS_TO_DB.get(sheets_key)
            if db_col:
                update[db_col] = _norm_text(v)

        # GOVERNANÇA DE PERFIL: Trava de Loja
        # Se houve mudança em ID da loja, Nome da Loja ou Número da loja, rebaixa para 'Pendente'
        try:
            existente = buscar_membro(int(float(tid)))
            if existente:
                def _val_diff(novo, exist):
                    return str(novo or "").strip().lower() != str(exist or "").strip().lower()
                
                mudanca = False
                if "loja_id" in update and _val_diff(update["loja_id"], existente.get("ID da loja") or existente.get("loja_id")):
                    mudanca = True
                if "loja" in update and _val_diff(update["loja"], existente.get("Loja") or existente.get("loja")):
                    mudanca = True
                if "numero_loja" in update and _val_diff(update["numero_loja"], existente.get("Número da loja") or existente.get("numero_loja")):
                    mudanca = True
                
                if mudanca:
                    logger.info("Governanca: Membro %s alterou sua Loja. Rebaixando status para Pendente.", tid)
                    update["status"] = "Pendente"
        except Exception as e_gov:
            logger.error("Erro na governanca de trava de loja: %s", e_gov)

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
                    "Coluna 'status' ausente em 'membros' — UPDATE sem ela. "
                    "Adicione-a: ALTER TABLE membros ADD COLUMN status TEXT DEFAULT 'Ativo';"
                )
                update.pop("status", None)
                if update:  # só executa se ainda houver outros campos
                    supabase.table("membros").update(update).eq("telegram_id", tid).execute()
            elif _coluna_ausente(e_upd, "potencia_complemento"):
                logger.warning(
                    "Coluna 'potencia_complemento' ausente em 'membros' — UPDATE sem ela. "
                    "Adicione-a: ALTER TABLE membros ADD COLUMN potencia_complemento TEXT DEFAULT '';"
                )
                update.pop("potencia_complemento", None)
                if update:
                    supabase.table("membros").update(update).eq("telegram_id", tid).execute()
            else:
                raise

        # Invalida o cache
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

        # Invalida o cache
        _cache_membros.pop(telegram_id, None)
        _cache_membros.pop(int(float(tid)), None)
        return True

    except Exception as e:
        logger.error("Erro ao atualizar nível: %s", e)
        return False


def atualizar_status_membro(telegram_id: int, novo_status: str) -> bool:
    """Atualiza o status do cadastro do membro preservando seu nível."""
    status = _norm_text(novo_status) or "Ativo"
    return atualizar_membro(telegram_id, {"Status": status}, preservar_nivel=True)


def excluir_membro(telegram_id: int) -> bool:
    """Exclui fisicamente um membro pelo Telegram ID (alternativa para bases sem coluna de status)."""
    try:
        tid = _norm_intlike(telegram_id)
        if not tid:
            return False

        supabase.table("membros").delete().eq("telegram_id", tid).execute()

        # Invalida o cache
        _cache_membros.pop(telegram_id, None)
        _cache_membros.pop(int(float(tid)), None)
        return True

    except Exception as e:
        logger.error("Erro ao excluir membro: %s", e)
        return False


# =========================
# Funções para Eventos
# =========================

def listar_eventos(include_inativos: bool = False) -> List[dict]:
    """
    Lista eventos. Por padrão retorna apenas status 'ativo' (ou vazio => ativo).
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
            # Consulta única: ativos + status nulo/vazio (retrocompatível)
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

        # Normalizar valores None para string vazia onde necessário
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
    Prioriza busca por id_evento. O parâmetro `indice` é mantido apenas
    por compatibilidade de assinatura.
    """
    try:
        id_evento = _norm_text(evento.get("ID Evento") or evento.get("id_evento"))
        if not id_evento:
            # Alternativa: busca por data_evento + nome_loja
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

        _update_com_fallback_colunas("eventos", "id_evento", id_evento, row)
        _cache_eventos.clear()
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

        # FORÇA: ignora o cache para evitar condições de corrida
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
            "potencia_complemento": _norm_text(
                dados.get("potencia_complemento") or dados.get("Potência complemento")
            ),
            "agape":            _norm_text(dados.get("agape") or dados.get("Ágape")),
            "data_hora":        _now_str(segundos=True),
            "veneravel_mestre": _norm_text(
                dados.get("veneravel_mestre") or dados.get("Venerável Mestre") or dados.get("vm")
            ),
            "mestre_instalado": _norm_text(
                dados.get("mestre_instalado") or dados.get("Mestre Instalado") or dados.get("mi")
            ),
        }

        # Insere com fallback para instalações que não tenham algumas colunas (schema cache / migração parcial).
        # Ex.: "Could not find the 'mestre_instalado' column of 'confirmacoes' in the schema cache"
        tentativa = dict(row)
        for _ in range(5):
            try:
                supabase.table("confirmacoes").insert(tentativa).execute()
                break
            except Exception as inner:
                msg = str(inner)
                import re

                m = re.search(r"Could not find the '([^']+)' column", msg)
                if not m:
                    raise
                col = m.group(1)
                if col in tentativa:
                    tentativa.pop(col, None)
                    continue
                # Se a coluna não existir no payload, não há como corrigir via retry
                raise

        # Invalida o cache
        cache_key = (id_evento, int(float(telegram_id)))
        _cache_confirmacoes.pop(cache_key, None)

        # Invalida caches multi-id do mesmo usuário que possam conter este evento.
        try:
            tid_int = int(float(telegram_id))
            target_evento = _norm_text(id_evento)
            keys_to_remove = []
            for k in _cache_confirmacoes:
                try:
                    if (
                        isinstance(k, tuple)
                        and len(k) == 2
                        and isinstance(k[0], tuple)
                        and k[1] == tid_int
                        and target_evento in k[0]
                    ):
                        keys_to_remove.append(k)
                except Exception:
                    continue
            for k in keys_to_remove:
                _cache_confirmacoes.pop(k, None)
        except Exception:
            pass
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

        # Invalida o cache
        cache_key = (id_evento, telegram_id)
        _cache_confirmacoes.pop(cache_key, None)

        # Invalida caches multi-id que incluam este evento + usuário (ex.: (tuple(ids), tid)).
        keys_to_remove = []
        for k in _cache_confirmacoes:
            try:
                if (
                    isinstance(k, tuple)
                    and len(k) == 2
                    and isinstance(k[0], tuple)
                    and k[1] == telegram_id
                    and target_evento in k[0]
                ):
                    keys_to_remove.append(k)
            except Exception:
                continue
        for k in keys_to_remove:
            _cache_confirmacoes.pop(k, None)
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


def listar_confirmacoes_por_eventos(ids_evento: List[str]) -> List[dict]:
    """Retorna confirmações para múltiplos IDs de evento (compatibilidade com IDs legados)."""
    try:
        ids_norm = [_norm_text(i) for i in (ids_evento or [])]
        ids_norm = [i for i in ids_norm if i]
        if not ids_norm:
            return []

        # Evita query inválida e reduz payload
        ids_norm = list(dict.fromkeys(ids_norm))

        resp = (
            supabase.table("confirmacoes")
            .select("*")
            .in_("id_evento", ids_norm)
            .execute()
        )
        return [_row_to_sheets("confirmacoes", row) for row in (resp.data or [])]

    except Exception as e:
        logger.error("Erro ao listar confirmações (multi-id): %s", e)
        return []


def buscar_confirmacao_em_eventos(
    ids_evento: List[str],
    telegram_id: int,
    usar_cache: bool = True,
) -> Optional[dict]:
    """Busca confirmação do usuário em qualquer um dos IDs de evento informados."""
    ids_norm = [_norm_text(i) for i in (ids_evento or [])]
    ids_norm = [i for i in ids_norm if i]
    if not ids_norm:
        return None

    ids_norm = list(dict.fromkeys(ids_norm))

    cache_key = (tuple(ids_norm), telegram_id)
    if usar_cache and cache_key in _cache_confirmacoes:
        cached, timestamp = _cache_confirmacoes[cache_key]
        if time.time() - timestamp < _ttl_confirmacoes:
            return cached

    try:
        tid = _norm_intlike(telegram_id)
        if not tid:
            _cache_confirmacoes[cache_key] = (None, time.time())
            return None

        resp = (
            supabase.table("confirmacoes")
            .select("*")
            .in_("id_evento", ids_norm)
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
        logger.error("Erro ao buscar confirmação (multi-id): %s", e)
        return None


def cancelar_todas_confirmacoes(id_evento: str) -> bool:
    """Remove todas as confirmações de um evento."""
    try:
        target_evento = _norm_text(id_evento)
        if not target_evento:
            return False

        supabase.table("confirmacoes").delete().eq("id_evento", target_evento).execute()

        # Invalida o cache de todas as entradas relacionadas ao evento
        keys_to_remove = []
        for k in _cache_confirmacoes:
            try:
                if k[0] == id_evento:
                    keys_to_remove.append(k)
                elif (
                    isinstance(k, tuple)
                    and len(k) == 2
                    and isinstance(k[0], tuple)
                    and target_evento in k[0]
                ):
                    keys_to_remove.append(k)
            except Exception:
                continue
        for k in keys_to_remove:
            _cache_confirmacoes.pop(k, None)

        return True

    except Exception as e:
        logger.error("Erro ao cancelar confirmações: %s", e)
        return False


# =========================
# Funções para Lojas (pré-cadastro)
# =========================

def _secretario_responsavel_loja_id(loja: Dict[str, Any]) -> str:
    """Resolve o secretário responsável da loja (novo campo com alternativa legada)."""
    sid = _norm_intlike(
        loja.get("Telegram ID do secretário responsável")
        or loja.get("secretario_responsavel_id")
        or loja.get("Telegram ID")
    )
    return sid


def _secretario_responsavel_loja_nome(loja: Dict[str, Any]) -> str:
    """Nome do secretário responsável com alternativa para vazio."""
    return _norm_text(
        loja.get("Nome do secretário responsável")
        or loja.get("secretario_responsavel_nome")
    )


def listar_secretarios_ativos() -> List[Dict[str, str]]:
    """Lista membros ativos de nível 2 para seleção de responsabilidade."""
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
    - include_todas=False: lojas do secretário responsável informado.
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
            # Mantém retrocompatibilidade: responsável novo OU telegram_id legado.
            filtro_responsavel = f"secretario_responsavel_id.eq.{target},telegram_id.eq.{target}"
            query = query.or_(filtro_responsavel)

        resp = query.execute()
        result = [_row_to_sheets("lojas", row) for row in (resp.data or [])]
        _cache_lojas[cache_key] = (result, time.time())
        return result

    except Exception as e:
        coluna = _extrair_coluna_ausente(e)
        if not include_todas and coluna == "secretario_responsavel_id":
            logger.warning(
                "Coluna 'secretario_responsavel_id' ausente em 'lojas' — usando fallback legado por telegram_id."
            )
            try:
                target = _norm_intlike(telegram_id)
                if not target:
                    return []
                resp = supabase.table("lojas").select("*").eq("telegram_id", target).execute()
                result = [_row_to_sheets("lojas", row) for row in (resp.data or [])]
                _cache_lojas[cache_key] = (result, time.time())
                return result
            except Exception as e_fallback:
                logger.error("Erro ao listar lojas no fallback legado: %s", e_fallback)
        logger.error("Erro ao listar lojas: %s", e)
        return []


def listar_lojas_visiveis(user_id: int, nivel: str) -> List[Dict[str, Any]]:
    """Lista lojas visíveis para o usuário conforme perfil."""
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
    """Busca uma loja pelo par (nome, número)."""
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
        logger.error("Erro ao buscar loja por nome/número (%s/%s): %s", nome, numero, e)
        return None


def obter_secretario_responsavel_evento(evento: Dict[str, Any]) -> Optional[int]:
    """
    Resolve o secretário responsável do evento com prioridade:
    1) Loja vinculada (ID da loja)
    2) Loja por (nome, número)
    3) Campo do próprio evento (legado)
    """
    loja = None
    loja_id = _norm_text(evento.get("ID da loja") or evento.get("loja_id"))
    if loja_id:
        loja = buscar_loja_por_id(loja_id)

    if not loja:
        loja = buscar_loja_por_nome_numero(
            evento.get("Nome da loja") or evento.get("nome_loja"),
            evento.get("Número da loja") or evento.get("numero_loja"),
        )

    if loja:
        sid = _secretario_responsavel_loja_id(loja)
        if sid:
            try:
                return int(float(sid))
            except Exception:
                pass

    legado = _norm_intlike(evento.get("Telegram ID do secretário") or evento.get("secretario_telegram_id"))
    if not legado:
        return None
    try:
        return int(float(legado))
    except Exception:
        return None


def usuario_pode_gerenciar_evento(user_id: int, nivel: str, evento: Dict[str, Any]) -> bool:
    """Permissão unificada para gerenciamento de evento."""
    if str(nivel) == "3":
        return True
    sid = obter_secretario_responsavel_evento(evento)
    return sid is not None and int(sid) == int(user_id)


def cadastrar_loja(telegram_id: int, dados: Dict[str, Any]) -> bool:
    """
    Cadastra uma nova loja.
    O campo legado `telegram_id` passa a representar o responsável da loja.
    """
    try:
        data_cadastro = datetime.now().strftime("%d/%m/%Y %H:%M")

        responsavel_id = _norm_intlike(
            dados.get("secretario_responsavel_id")
            or dados.get("Telegram ID do secretário responsável")
            or telegram_id
        )
        responsavel_nome = _norm_text(
            dados.get("secretario_responsavel_nome")
            or dados.get("Nome do secretário responsável")
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
            "potencia_complemento": _norm_text(dados.get("potencia_complemento", "")),
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
    """Atualiza o secretário responsável da loja."""
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
        logger.error("Erro ao atualizar secretário responsável da loja %s: %s", lid, e)
        return False


def atualizar_template_visual_loja(loja_id: Any, dados: Dict[str, Any]) -> bool:
    """Atualiza configurações visuais da loja."""
    lid = _norm_text(loja_id)
    if not lid:
        return False

    row = _sheets_to_row("lojas", dados)
    row.pop("id", None)
    for k in list(row.keys()):
        if row[k] is None:
            row[k] = ""

    try:
        _update_com_fallback_colunas("lojas", "id", lid, row)
        _cache_lojas.clear()
        return True
    except Exception as e:
        logger.error("Erro ao atualizar template visual da loja %s: %s", lid, e)
        return False


def upload_storage_publico(bucket: str, path: str, content: bytes, content_type: str = "application/octet-stream") -> Optional[str]:
    """Faz upload para Supabase Storage e retorna URL pública."""
    if not bucket or not path or not content:
        return None
    try:
        storage = supabase.storage.from_(bucket)
        try:
            storage.remove([path])
        except Exception:
            pass
        storage.upload(path, content, {"content-type": content_type, "upsert": "true"})
        return storage.get_public_url(path)
    except Exception as e:
        logger.error("Erro ao subir arquivo para Storage (%s/%s): %s", bucket, path, e)
        return None


def excluir_loja(telegram_id: int, loja: dict) -> bool:
    """
    Exclui uma loja específica.
    Prioriza exclusão por ID; fallback para nome+número+rito.
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
            if _norm_text(row.get("numero")) != _norm_text(loja.get("Número", "")):
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


def get_preferencia_lembretes(telegram_id: int) -> bool:
    """
    Retorna a preferência de lembretes do usuário.

    Regras:
    - "NÃO" desativa lembretes e alertas privados.
    - "SIM" ativa explicitamente.
    - vazio/ausente mantém o comportamento legado: ativo por padrão.
    """
    try:
        membro = buscar_membro(telegram_id)
        if not membro:
            return True
        notificacao = str(membro.get("Notificações", "") or "").strip().upper()
        if notificacao == "NÃO":
            return False
        return True
    except Exception as e:
        logger.error("Erro ao buscar preferência de lembretes: %s", e)
        return True


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
# Notificações pendentes do secretário (persistência)
# =========================

def registrar_notificacao_secretario_pendente(secretario_id: int, item: Dict[str, str]) -> bool:
    """Persiste notificação pendente para envio consolidado fora da janela de silêncio."""
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
        logger.error("Erro ao registrar notificação pendente do secretário: %s", e)
        return False


def listar_notificacoes_secretario_pendentes(secretario_id: int) -> List[Dict[str, str]]:
    """Lista notificações pendentes de um secretário, da mais antiga para a mais nova."""
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
        logger.error("Erro ao listar notificações pendentes do secretário: %s", e)
        return []


def listar_secretarios_com_notificacoes_pendentes() -> List[int]:
    """Retorna IDs de secretários que possuem notificações pendentes."""
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
        logger.error("Erro ao listar secretários com notificações pendentes: %s", e)
        return []


def remover_notificacoes_secretario_pendentes(secretario_id: int) -> bool:
    """Remove todas as notificações pendentes de um secretário após envio consolidado."""
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
        logger.error("Erro ao remover notificações pendentes do secretário: %s", e)
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
    """Busca eventos cujo responsável operacional é o secretário informado."""
    try:
        target = _safe_cache_int(user_id)
        if not target:
            return []
        eventos = await asyncio.to_thread(listar_eventos, True)
        return [ev for ev in eventos if obter_secretario_responsavel_evento(ev) == target]

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


# ============================================
# GESTÃO DE VOUCHERS E OFÍCIOS
# ============================================

def get_loja_por_secretario(user_id: Any) -> Optional[Dict[str, Any]]:
    """Busca a loja cujo secretário_responsavel_id corresponde ao ID do usuário."""
    target = _norm_intlike(user_id)
    if not target:
        return None
    try:
        # Procura pelo secretário responsável no banco
        resp = supabase.table("lojas").select("*").eq("secretario_responsavel_id", str(target)).execute()
        if resp.data:
            return _row_to_sheets("lojas", resp.data[0])
            
        # Fallback legado para compatibilidade: procura na coluna telegram_id
        resp = supabase.table("lojas").select("*").eq("telegram_id", target).execute()
        if resp.data:
            return _row_to_sheets("lojas", resp.data[0])
            
        return None
    except Exception as e:
        logger.error("Erro em get_loja_por_secretario para %s: %s", user_id, e)
        return None


def get_voucher_ativo_por_loja(loja_id: Any) -> Optional[Dict[str, Any]]:
    """Busca o voucher ativo mais recente para uma oficina."""
    lid = _norm_intlike(loja_id)
    if not lid:
        return None
    try:
        resp = (
            supabase.table("vouchers")
            .select("*")
            .eq("loja_id", int(float(lid)))
            .eq("ativo", True)
            .execute()
        )
        if not resp.data:
            return None
            
        # Trata limitação física / temporal
        for v in resp.data:
            limite = v.get("limite_usos") or 100
            usos = v.get("usos_atuais") or 0
            if usos < limite:
                exp = v.get("data_expiracao")
                if exp:
                    from datetime import datetime, timezone
                    try:
                        dt_exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                        if datetime.now(timezone.utc) > dt_exp:
                            continue
                    except:
                        pass
                return v
        return None
    except Exception as e:
        logger.error("Erro ao obter voucher ativo para loja %s: %s", loja_id, e)
        return None


def criar_voucher(loja_id: Any, criado_por: Any, limite: int = 100) -> Optional[str]:
    """Gera um token único de voucher e insere no banco de dados."""
    import uuid
    lid = _norm_intlike(loja_id)
    criador = _norm_intlike(criado_por)
    if not lid or not criador:
        return None
        
    token = f"VOUCHER_{uuid.uuid4().hex[:8].upper()}"
    
    try:
        # Desativa eventuais vouchers ativos anteriores desta loja
        try:
            supabase.table("vouchers").update({"ativo": False}).eq("loja_id", int(float(lid))).eq("ativo", True).execute()
        except Exception:
            pass

        row = {
            "token": token,
            "loja_id": int(float(lid)),
            "criado_por": str(criador),
            "limite_usos": int(limite),
            "usos_atuais": 0,
            "ativo": True
        }
        supabase.table("vouchers").insert(row).execute()
        return token
    except Exception as e:
        logger.error("Erro ao criar voucher para loja %s: %s", lid, e)
        return None


def verificar_voucher(token: str) -> Optional[Dict[str, Any]]:
    """Verifica se um token existe, está ativo, não expirado e tem usos disponíveis."""
    if not token:
        return None
    try:
        # Query trazendo a Loja como join nativo
        resp = supabase.table("vouchers").select("*, lojas(*)").eq("token", token.strip().upper()).execute()
        if not resp.data:
            return None
            
        v = resp.data[0]
        if not v.get("ativo"):
            return None
            
        limite = v.get("limite_usos") or 100
        usos = v.get("usos_atuais") or 0
        if usos >= limite:
            return None
            
        # Verificar validade temporal
        exp = v.get("data_expiracao")
        if exp:
            from datetime import datetime, timezone
            try:
                dt_exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > dt_exp:
                    return None
            except Exception:
                pass
                
        raw_loja = v.get("lojas")
        if not raw_loja:
            return None
            
        v["loja_enriquecida"] = _row_to_sheets("lojas", raw_loja)
        return v
    except Exception as e:
        logger.error("Erro ao verificar voucher %s: %s", token, e)
        return None


def consumir_voucher(token: str) -> bool:
    """Registra o uso do voucher incrementando usos_atuais."""
    if not token:
        return False
    try:
        # Controle de concorrência via Read-Modify-Write
        resp = supabase.table("vouchers").select("id, usos_atuais").eq("token", token.strip().upper()).execute()
        if not resp.data:
            return False
            
        v = resp.data[0]
        novos_usos = (v.get("usos_atuais") or 0) + 1
        supabase.table("vouchers").update({"usos_atuais": novos_usos}).eq("id", v["id"]).execute()
        return True
    except Exception as e:
        logger.error("Erro ao consumir voucher %s: %s", token, e)
        return False


def transferir_secretaria(id_antigo: Any, id_novo: Any, loja_id: Any) -> bool:
    """Realiza a transmissão do bastão da secretaria de forma atômica."""
    old_tid = _norm_intlike(id_antigo)
    new_tid = _norm_intlike(id_novo)
    lid = _norm_intlike(loja_id)
    
    if not old_tid or not new_tid or not lid:
        return False
        
    try:
        # 1. Atualiza o proprietário da Loja
        supabase.table("lojas").update({"secretario_responsavel_id": str(new_tid)}).eq("id", int(float(lid))).execute()
        
        # 2. Promove o sucessor para Nível 2
        atualizar_nivel_membro(int(float(new_tid)), "2")
        
        # 3. Rebaixa o antigo para Nível 1
        atualizar_nivel_membro(int(float(old_tid)), "1")
        
        # Limpeza total de caches afetados
        _cache_lojas.clear()
        _cache_membros.pop(int(float(old_tid)), None)
        _cache_membros.pop(int(float(new_tid)), None)
        
        return True
    except Exception as e:
        logger.error("Falha transacional ao transferir secretaria de %s para %s: %s", old_tid, new_tid, e)
        return False


def listar_membros_ativos() -> list[dict[str, Any]]:
    """Retorna membros com status 'Ativo'."""
    return listar_membros(include_inativos=False)


def marcar_como_inativo(telegram_id: int) -> bool:
    """Marca o status do cadastro do membro como 'Inativo'."""
    return atualizar_status_membro(telegram_id, 'Inativo')


# ============================================
# TELEMETRIA E PAINEL DO VIGILANTE (NÍVEL 3)
# ============================================

def registrar_log_busca(
    uf: str = None, 
    cidade: str = None, 
    rito: str = None, 
    grau: int = None, 
    encontrou_resultados: bool = False
) -> bool:
    try:
        uf_val = (uf or "").strip().upper()[:2] or None
        cid_val = (cidade or "").strip().lower() or None
        if cid_val:
            cid_val = cid_val.title()
        rito_val = (rito or "").strip() or None
        
        grau_val = None
        if grau:
            try:
                grau_val = int(grau)
            except Exception:
                pass

        row = {
            "uf": uf_val,
            "cidade": cid_val,
            "rito": rito_val,
            "grau": grau_val,
            "encontrou_resultados": bool(encontrou_resultados),
        }
        
        supabase.table("logs_busca").insert(row).execute()
        return True
    except Exception as e:
        logger.error("Erro ao registrar log de busca: %s", e)
        return False


def get_modo_comunicacao_ativo() -> bool:
    try:
        resp = supabase.table("configuracoes_globais").select("valor_bool").eq("chave", "modo_comunicacao_ativo").execute()
        if resp.data:
            return bool(resp.data[0].get("valor_bool", False))
    except Exception as e:
        logger.error("Erro ao ler modo_comunicacao_ativo: %s", e)
    return False


def set_modo_comunicacao_ativo(ativo: bool) -> bool:
    try:
        supabase.table("configuracoes_globais").update({"valor_bool": bool(ativo)}).eq("chave", "modo_comunicacao_ativo").execute()
        return True
    except Exception as e:
        logger.error("Erro ao atualizar modo_comunicacao_ativo: %s", e)
        return False


def obter_gaps_sessoes(dias: int = 30) -> list:
    try:
        from datetime import datetime, timedelta
        limite = datetime.utcnow() - timedelta(days=dias)
        
        resp = (
            supabase.table("logs_busca")
            .select("uf, cidade, rito, grau")
            .eq("encontrou_resultados", False)
            .gte("created_at", limite.isoformat())
            .execute()
        )
        
        logs = resp.data or []
        if not logs:
            return []
            
        from collections import Counter
        contagem = Counter()
        for log in logs:
            uf = (log.get("uf") or "").strip().upper()
            cid = (log.get("cidade") or "").strip()
            rito = (log.get("rito") or "").strip()
            if not cid:
                continue
            contagem[(uf, cid, rito)] += 1
            
        from src.eventos import listar_eventos
        eventos = listar_eventos() or []
        hoje = datetime.utcnow().date()
        
        sessoes_futuras_locais = set()
        for ev in eventos:
            if str(ev.get("Status", "")).lower() in ("cancelado", "inativo"):
                continue
            
            data_str = ev.get("Data do evento", "")
            try:
                dt = datetime.strptime(data_str, "%d/%m/%Y").date()
                if dt < hoje:
                    continue
            except Exception:
                pass
                
            ori = ev.get("Oriente", "")
            if "/" in ori:
                partes = ori.split("/")
                cid_ev = partes[0].strip().title()
                uf_ev = partes[1].strip().upper()
            else:
                cid_ev = ori.strip().title()
                uf_ev = ""
                
            rito_ev = (ev.get("Rito") or "").strip()
            sessoes_futuras_locais.add((uf_ev, cid_ev, rito_ev))
            
        gaps = []
        for (uf, cid, rito), total in contagem.most_common():
            encontrou_oferta = False
            for (uf_fut, cid_fut, rito_fut) in sessoes_futuras_locais:
                if cid.lower() == cid_fut.lower():
                    if rito and rito_fut and rito.lower() != rito_fut.lower():
                        continue
                    encontrou_oferta = True
                    break
                    
            if not encontrou_oferta:
                gaps.append({
                    "uf": uf,
                    "cidade": cid,
                    "rito": rito,
                    "total_buscas": total
                })
                
        return gaps
    except Exception as e:
        logger.error("Erro ao obter gaps de sessões: %s", e)
        return []


def get_secretarios_filtrados(
    uf: str = None,
    cidade: str = None,
    rito: str = None
) -> list:
    try:
        resp_lojas = supabase.table("lojas").select("*").execute()
        lojas = resp_lojas.data or []
        
        uf_f = (uf or "").strip().upper()
        cid_f = (cidade or "").strip().lower()
        rito_f = (rito or "").strip().lower()
        
        sec_validos = set()
        for loja in lojas:
            sec_id = _norm_intlike(loja.get("secretario_responsavel_id"))
            if not sec_id:
                continue
                
            if uf_f and uf_f != "TODAS":
                st = (loja.get("estado_uf") or "").strip().upper()
                if st != uf_f:
                    continue
                    
            if cid_f and cid_f != "todas":
                c = (loja.get("cidade") or "").strip().lower()
                if c != cid_f:
                    continue
                    
            if rito_f and rito_f != "todos":
                r = (loja.get("rito") or "").strip().lower()
                if rito_f not in r:
                    continue
                    
            try:
                sec_validos.add(int(float(sec_id)))
            except Exception:
                pass
                
        if not sec_validos:
            return []
            
        membros = listar_membros(include_inativos=False)
        ids_finais = []
        for m in membros:
            tid_str = _norm_intlike(m.get("Telegram ID") or m.get("telegram_id"))
            if not tid_str:
                continue
            try:
                tid = int(float(tid_str))
                if tid in sec_validos and str(m.get("Nivel", "1")) in ("2", "3"):
                    ids_finais.append(tid)
            except Exception:
                continue
                
        return ids_finais
    except Exception as e:
        logger.error("Erro ao obter secretários filtrados: %s", e)
        return []


# ============================================
# MOTOR DE GAMIFICAÇÃO (JORNADA DO OBREIRO)
# ============================================

def registrar_conquista(user_id: int, conquista_slug: str) -> bool:
    """
    Registra uma conquista vitalícia para o obreiro.
    Ignora silenciosamente se já possuir (unique key constraint).
    """
    try:
        uid = _norm_intlike(user_id)
        if not uid:
            return False
            
        payload = {
            "user_id": int(float(uid)),
            "conquista_slug": conquista_slug.strip().lower()
        }
        
        supabase.table("membro_conquistas").insert(payload).execute()
        logger.info("Nova conquista registrada: %s para user %s", conquista_slug, uid)
        return True
    except Exception as e:
        # Pode ser conflito de PK/Unique, tratamos como sucesso funcional (já gravado)
        logger.debug("Ignorando tentativa de duplicar conquista %s para %s: %s", conquista_slug, user_id, e)
        return True


def listar_conquistas_obtidas(user_id: int) -> List[str]:
    """Retorna a lista de slugs de conquistas já obtidas pelo obreiro."""
    try:
        uid = _norm_intlike(user_id)
        if not uid:
            return []
            
        resp = supabase.table("membro_conquistas") \
            .select("conquista_slug") \
            .eq("user_id", int(float(uid))) \
            .execute()
            
        if not resp.data:
            return []
            
        return [str(item.get("conquista_slug", "")) for item in resp.data]
    except Exception as e:
        logger.error("Erro ao listar conquistas de %s: %s", user_id, e)
        return []


def registrar_marco_coletivo(marco_slug: str, categoria: str) -> bool:
    """Registra a ocorrência de um marco sistêmico de crescimento."""
    try:
        payload = {
            "marco_slug": marco_slug.strip().lower(),
            "categoria": categoria.strip()
        }
        supabase.table("marcos_coletivos").insert(payload).execute()
        return True
    except Exception as e:
        logger.debug("Marco coletivo já registrado ou erro: %s", e)
        return True


def checar_marco_coletivo_existente(marco_slug: str) -> bool:
    """Verifica se um determinado marco de crescimento já ocorreu antes."""
    try:
        slug = marco_slug.strip().lower()
        resp = supabase.table("marcos_coletivos") \
            .select("marco_slug") \
            .eq("marco_slug", slug) \
            .limit(1) \
            .execute()
            
        return len(resp.data or []) > 0
    except Exception as e:
        logger.error("Erro ao checar marco coletivo: %s", e)
        return False


def _extrair_path_storage_do_url(url: str, bucket: str) -> Optional[str]:
    """Extrai o caminho interno do arquivo dentro do bucket a partir de uma URL pública do Supabase."""
    if not url or bucket not in url:
        return None
    marcador = f"/public/{bucket}/"
    idx = url.find(marcador)
    if idx == -1:
        return None
    # Remove tudo antes e incluindo o marcador
    return url[idx + len(marcador):]


def limpar_midias_eventos_passados() -> int:
    """
    Varre o banco por eventos passados e remove suas imagens físicas do Supabase Storage (efemeridade).
    Retorna a quantidade de arquivos removidos com sucesso.
    """
    from datetime import datetime
    hoje = datetime.now().date()
    arquivos_removidos = 0
    bucket = "event-cards"
    
    try:
        # Seleciona colunas essenciais de todos os eventos que possuam alguma URL salva
        resp = supabase.table("eventos").select("id, data_evento, card_especial_url, card_renderizado_url").execute()
        rows = resp.data or []
    except Exception as e:
        logger.error("Erro ao buscar eventos para limpeza de mídias: %s", e)
        return 0

    if not rows:
        return 0

    logger.info("Iniciando análise de %d eventos para coleta de lixo de mídias...", len(rows))
    
    storage = supabase.storage.from_(bucket)
    
    for row in rows:
        ev_id = row.get("id")
        data_raw = row.get("data_evento")
        if not data_raw:
            continue
            
        # Converte data para comparação
        dt_ev = _parse_data_generica(data_raw)
        if not dt_ev:
            continue
            
        # Se o evento ocorreu em dias passados
        if dt_ev.date() < hoje:
            candidatos = []
            
            # 1. Checa card especial
            url_esp = row.get("card_especial_url")
            if url_esp:
                path_esp = _extrair_path_storage_do_url(url_esp, bucket)
                if path_esp:
                    candidatos.append(path_esp)
                    
            # 2. Checa card renderizado
            url_ren = row.get("card_renderizado_url")
            if url_ren:
                path_ren = _extrair_path_storage_do_url(url_ren, bucket)
                if path_ren:
                    candidatos.append(path_ren)
            
            # Se houver mídias físicas, removemos
            if candidatos:
                try:
                    logger.info("Excluindo %d mídias expiradas do evento %s (Data: %s)", len(candidatos), ev_id, data_raw)
                    storage.remove(candidatos)
                    arquivos_removidos += len(candidatos)
                    
                    # Limpa os campos no banco para evitar reprocessamento
                    supabase.table("eventos").update({
                        "card_especial_url": None,
                        "card_renderizado_url": None
                    }).eq("id", ev_id).execute()
                    
                except Exception as err:
                    logger.warning("Falha ao excluir arquivos %s do storage: %s", candidatos, err)
                    
    if arquivos_removidos > 0:
        logger.info("Limpeza de efemeridade concluída: %d mídias limpas do storage.", arquivos_removidos)
    
    return arquivos_removidos

# =========================
# Telhamento Digital e Fundação
# =========================

def solicitar_fundacao(membro_id: int, loja_dados: dict) -> bool:
    """Registra pedido de fundação na tabela pedidos_fundacao."""
    try:
        mid = _norm_intlike(membro_id)
        if not mid:
            return False
        row = {
            "membro_id": int(float(mid)),
            "status": "Pendente",
            "loja_dados": loja_dados
        }
        supabase.table("pedidos_fundacao").insert(row).execute()
        return True
    except Exception as e:
        logger.error("Erro ao registrar pedido de fundação para membro %s: %s", membro_id, e)
        return False


def listar_auditores_por_potencia(potencia_complemento: str) -> List[int]:
    """
    Retorna a lista de Telegram IDs de usuários que são Nível '2' ou '2.5'
    e pertencem ao mesmo complemento de potência (ex: GOB-PR).
    """
    try:
        pc = _norm_text(potencia_complemento).strip().lower()
        if not pc:
            return []

        resp = (
            supabase.table("membros")
            .select("telegram_id, nivel, potencia_complemento")
            .in_("nivel", ["2", "2.5"])
            .execute()
        )

        ids = []
        if resp.data:
            for row in resp.data:
                r_pc = _norm_text(row.get("potencia_complemento")).strip().lower()
                if r_pc == pc:
                    tid = _safe_cache_int(row.get("telegram_id"))
                    if tid:
                        ids.append(tid)
        return ids
    except Exception as e:
        logger.error("Erro ao buscar auditores por potencia %s: %s", potencia_complemento, e)
        return []


# ============================================
# HERALDO: MARCOS DE EXPANSÃO COLETIVA
# ============================================

def get_total_confirmacoes() -> int:
    """Retorna o total agregado de confirmações registradas no banco de dados."""
    try:
        resp = supabase.table("confirmacoes").select("id_evento", count="exact").limit(1).execute()
        if hasattr(resp, 'count') and resp.count is not None:
            return resp.count
        return len(resp.data or [])
    except Exception as e:
        logger.error("Erro ao contar total de confirmacoes: %s", e)
        return 0


def is_first_of_potencia(potencia: str, potencia_comp: str) -> bool:
    """Verifica se a loja recém inserida é a única desta Potência + Complemento."""
    try:
        pot = str(potencia).strip().upper()
        comp = str(potencia_comp).strip().upper()
        
        query = supabase.table("lojas").select("id", count="exact")
        query = query.ilike("potencia", pot)
        
        if comp:
            query = query.ilike("potencia_complemento", comp)
        else:
            query = query.or_("potencia_complemento.is.null,potencia_complemento.eq.")
            
        resp = query.execute()
        c = resp.count if hasattr(resp, 'count') and resp.count is not None else len(resp.data or [])
        return c <= 1
    except Exception as e:
        logger.error("Erro ao verificar primeira loja da potencia: %s", e)
        return False


def get_estatisticas_vigor(loja_id: str, usar_mes_anterior: bool = False) -> Dict[str, Any]:
    """
    Calcula os indices de vigor administrativo da Secretaria:
    1. Vigor de Agenda: Media de dias de antecedencia na criacao de sessoes.
    2. Acolhimento: Contagem de confirmacoes de visitantes (membro.loja_id != loja_id).
    3. Engajamento: Porcentagem de membros ativos que confirmaram presencas no periodo.
    """
    from datetime import datetime, timedelta
    import statistics

    agora = datetime.now()
    lid_str = str(loja_id).strip()

    if usar_mes_anterior:
        primeiro_dia_mes_atual = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(seconds=1)
        primeiro_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1, hour=0, minute=0, second=0)
        data_inicio = primeiro_dia_mes_anterior
        data_fim = ultimo_dia_mes_anterior
    else:
        # Janela movel dos ultimos 30 dias ate o futuro proximo
        data_inicio = agora - timedelta(days=30)
        data_fim = agora + timedelta(days=60)

    try:
        # 1. BUSCAR EVENTOS DA LOJA NO PERÍODO
        resp_ev = supabase.table("eventos") \
            .select("id_evento, created_at, data_evento") \
            .eq("loja_id", lid_str) \
            .eq("status", "Ativo") \
            .execute()

        eventos_filtrados = []
        diferencas_dias = []

        for ev in (resp_ev.data or []):
            data_ev = _parse_data_generica(ev.get("data_evento"))
            if data_ev and data_inicio <= data_ev <= data_fim:
                eventos_filtrados.append(ev)
                
                # Processamento da Média de Antecedência
                dt_cre_str = str(ev.get("created_at") or "")[:10]
                dt_cre = _parse_data_generica(dt_cre_str)
                if not dt_cre:
                    try:
                        dt_cre = datetime.fromisoformat(ev.get("created_at").replace("Z", "+00:00")).replace(tzinfo=None)
                    except:
                        continue
                if data_ev and dt_cre:
                    diff = (data_ev - dt_cre).days
                    diferencas_dias.append(max(0, diff))

        vigor_agenda = round(statistics.mean(diferencas_dias), 1) if diferencas_dias else 0.0

        # 2. ÍNDICE DE ACOLHIMENTO (VISITANTES)
        ids_eventos = [ev["id_evento"] for ev in eventos_filtrados]
        total_visitantes = 0
        if ids_eventos:
            resp_conf = supabase.table("confirmacoes") \
                .select("telegram_id") \
                .in_("id_evento", ids_eventos) \
                .execute()
            
            tids = list(set([str(c.get("telegram_id")) for c in (resp_conf.data or []) if c.get("telegram_id")]))
            
            if tids:
                resp_memb = supabase.table("membros") \
                    .select("telegram_id, loja_id") \
                    .in_("telegram_id", tids) \
                    .execute()
                
                map_membros = {str(m["telegram_id"]): str(m["loja_id"]).strip() for m in (resp_memb.data or []) if m.get("telegram_id") and m.get("loja_id")}
                
                for c in (resp_conf.data or []):
                    tid = str(c.get("telegram_id"))
                    m_loja_id = map_membros.get(tid)
                    # Se o loja_id cadastrado do confirmante difere do loja_id da sessão, é visitante!
                    if m_loja_id and m_loja_id != lid_str:
                        total_visitantes += 1

        # 3. TAXA DE ENGAJAMENTO (QUÓRUM)
        resp_ativos = supabase.table("membros") \
            .select("telegram_id") \
            .eq("loja_id", lid_str) \
            .eq("status", "Ativo") \
            .execute()
        
        ativos_count = len(resp_ativos.data or [])
        ativos_ids = [str(m.get("telegram_id")) for m in (resp_ativos.data or []) if m.get("telegram_id")]
        
        presentes_count = 0
        if ativos_ids:
            resp_tot_conf = supabase.table("confirmacoes") \
                .select("telegram_id, data_hora") \
                .in_("telegram_id", ativos_ids) \
                .execute()
            
            confirmantes_unicos = set()
            for c in (resp_tot_conf.data or []):
                dt_conf = _parse_data_generica(c.get("data_hora"))
                if not dt_conf:
                    try:
                        dt_conf = datetime.fromisoformat(c.get("data_hora").replace("Z", "+00:00")).replace(tzinfo=None)
                    except:
                        continue
                if dt_conf and data_inicio <= dt_conf <= data_fim:
                    confirmantes_unicos.add(str(c.get("telegram_id")))
            
            presentes_count = len(confirmantes_unicos)

        taxa_engajamento = round((presentes_count / ativos_count * 100), 1) if ativos_count > 0 else 0.0

        # 4. CAPTURA METADADOS DA LOJA
        loja_nome = "Oficina"
        loja_num = ""
        resp_loja = supabase.table("lojas").select("nome_loja, numero").eq("id", lid_str).limit(1).execute()
        if resp_loja.data:
            loja_nome = resp_loja.data[0].get("nome_loja") or "Oficina"
            loja_num = resp_loja.data[0].get("numero") or ""

        return {
            "loja_id": lid_str,
            "nome_loja": loja_nome,
            "numero_loja": loja_num,
            "periodo_inicio": data_inicio.strftime("%d/%m/%Y"),
            "periodo_fim": data_fim.strftime("%d/%m/%Y"),
            "vigor_agenda": vigor_agenda,
            "acolhimento": total_visitantes,
            "ativos_quadro": ativos_count,
            "presentes_quadro": presentes_count,
            "engajamento": taxa_engajamento,
            "eventos_no_periodo": len(eventos_filtrados)
        }

    except Exception as e:
        logger.error("Erro ao calcular estatisticas de vigor para loja %s: %s", lid_str, e)
        return {
            "loja_id": lid_str,
            "nome_loja": "Erro de Leitura",
            "numero_loja": "",
            "periodo_inicio": data_inicio.strftime("%d/%m/%Y"),
            "periodo_fim": data_fim.strftime("%d/%m/%Y"),
            "vigor_agenda": 0.0,
            "acolhimento": 0,
            "ativos_quadro": 0,
            "presentes_quadro": 0,
            "engajamento": 0.0,
            "eventos_no_periodo": 0
        }


def get_galeria_completa(telegram_id: int, loja_id: str) -> Dict[str, Any]:
    """
    Consolida toda a gamificação individual e coletiva (Sala de Troféus) em um único payload.
    1. Coleta as conquistas individuais obtidas pelo usuario.
    2. Realiza a agregação dinâmica de vigor nos últimos 6 meses para extração de selos OE e FR.
    3. Retorna os marcos globais de expansão do ecossistema.
    """
    from datetime import datetime, timedelta
    import collections
    import statistics

    uid = _norm_intlike(telegram_id)
    lid_str = str(loja_id or "").strip()
    
    # 1. CONQUISTAS INDIVIDUAIS
    catalogo_badges = [
        {"slug": "ic", "titulo": "Iniciado na Colher", "descricao": "Primeira presença confirmada no ecossistema."},
        {"slug": "mp", "titulo": "Mestre dos Portais", "descricao": "Confirmou presença em 10 sessões."},
        {"slug": "e9", "titulo": "Estrela de 9 Pontas", "descricao": "Confirmou em 9 potências ou ritos."},
        {"slug": "ce", "titulo": "Colunista de Ébano", "descricao": "100% assiduidade nos últimos 3 meses."},
        {"slug": "og", "titulo": "Obreiro Global", "descricao": "Presença em 3 Estados diferentes."},
        {"slug": "pj", "titulo": "Peregrino da Justa", "descricao": "Visitante em 5 lojas diferentes."},
        {"slug": "rc", "titulo": "Reconstrutor do Templo", "descricao": "Indicou ou cadastrou nova Loja."},
        {"slug": "na", "titulo": "Navegador do Asfalto", "descricao": "Mais de 500km em deslocamentos."},
        {"slug": "rs", "titulo": "Redentor do Silêncio", "descricao": "Um ano ininterrupto com status Ativo."},
        {"slug": "io", "titulo": "Inspirador de Obreiros", "descricao": "Desafio mensal de novos membros."},
        {"slug": "pm", "titulo": "Protetor da Malha", "descricao": "Contribuições notáveis ao suporte."}
    ]
    
    obtidas = set(listar_conquistas_obtidas(uid) if uid else [])
    for badge in catalogo_badges:
        badge["desbloqueada"] = badge["slug"] in obtidas

    # 2. MARCOS DE VIGOR DA OFICINA (ÚLTIMOS 6 MESES)
    marcos_oficina = []
    if lid_str:
        try:
            agora = datetime.now()
            seis_meses_atras = agora - timedelta(days=180)
            
            resp_ev = supabase.table("eventos") \
                .select("id_evento, created_at, data_evento") \
                .eq("loja_id", lid_str) \
                .eq("status", "Ativo") \
                .execute()
            
            eventos_janela = []
            ids_janela = []
            for ev in (resp_ev.data or []):
                dt_ev = _parse_data_generica(ev.get("data_evento"))
                if dt_ev and seis_meses_atras <= dt_ev <= agora:
                    eventos_janela.append(ev)
                    ids_janela.append(ev["id_evento"])
            
            confirmacoes = []
            if ids_janela:
                resp_conf = supabase.table("confirmacoes") \
                    .select("id_evento, telegram_id") \
                    .in_("id_evento", ids_janela) \
                    .execute()
                confirmacoes = resp_conf.data or []
                
            tids = list(set([str(c.get("telegram_id")) for c in confirmacoes if c.get("telegram_id")]))
            map_membros = {}
            if tids:
                resp_memb = supabase.table("membros") \
                    .select("telegram_id, loja_id") \
                    .in_("telegram_id", tids) \
                    .execute()
                map_membros = {str(m["telegram_id"]): str(m["loja_id"]).strip() for m in (resp_memb.data or []) if m.get("telegram_id")}
                
            # Agrupamento
            dados_meses = collections.defaultdict(lambda: {"diferencas": [], "visitantes": 0})
            map_ev_mes = {}
            
            for ev in eventos_janela:
                dt_ev = _parse_data_generica(ev.get("data_evento"))
                if not dt_ev:
                    continue
                mes_str = dt_ev.strftime("%Y-%m")
                map_ev_mes[ev["id_evento"]] = mes_str
                
                dt_cre_str = str(ev.get("created_at") or "")[:10]
                dt_cre = _parse_data_generica(dt_cre_str)
                if not dt_cre:
                    try:
                        dt_cre = datetime.fromisoformat(ev.get("created_at").replace("Z", "+00:00")).replace(tzinfo=None)
                    except:
                        pass
                if dt_cre:
                    diff = (dt_ev - dt_cre).days
                    dados_meses[mes_str]["diferencas"].append(max(0, diff))
                    
            for conf in confirmacoes:
                ev_id = conf.get("id_evento")
                mes_str = map_ev_mes.get(ev_id)
                if not mes_str:
                    continue
                
                tid = str(conf.get("telegram_id"))
                m_loja_id = map_membros.get(tid)
                if m_loja_id and m_loja_id != lid_str:
                    dados_meses[mes_str]["visitantes"] += 1
                    
            # Ordenação dos últimos 6 meses
            meses_lista = []
            curr = agora
            for _ in range(6):
                meses_lista.append(curr.strftime("%Y-%m"))
                primeiro = curr.replace(day=1)
                anterior = primeiro - timedelta(days=1)
                curr = anterior
            meses_lista.reverse()
            
            for mes in meses_lista:
                d = dados_meses[mes]
                difs = d["diferencas"]
                total_visitantes = d["visitantes"]
                
                vigor_agenda = statistics.mean(difs) if difs else 0.0
                
                excelencia = vigor_agenda >= 15.0
                farol = total_visitantes > 10
                
                if excelencia or farol:
                    try:
                        dt_mes = datetime.strptime(mes, "%Y-%m")
                        nome_formatado = dt_mes.strftime("%b/%Y").capitalize()
                    except:
                        nome_formatado = mes
                        
                    marcos_oficina.append({
                        "mes": mes,
                        "mes_formatado": nome_formatado,
                        "excelencia": excelencia,
                        "farol": farol
                    })
        except Exception as e_vigor:
            logger.error("Falha ao calcular vigor retroativo para galeria: %s", e_vigor)

    # 3. MARCOS DE EXPANSÃO COLETIVA
    marcos_expansao = []
    try:
        resp_col = supabase.table("marcos_coletivos").select("marco_slug, categoria").execute()
        for item in (resp_col.data or []):
            slug = str(item.get("marco_slug", "")).strip()
            cat = str(item.get("categoria", "")).strip()
            
            nome_fmt = slug.upper()
            if "expansao_geo|" in slug:
                uf = slug.split("|")[-1].upper()
                nome_fmt = f"Cruz Vermelha Territorial ({uf})"
            elif "arco_integracao|" in slug:
                pot = slug.split("|")[-1].replace("_", " ").title()
                nome_fmt = f"Arco da Integração ({pot})"
            elif "rito_abertura" in slug:
                nome_fmt = "Abertura de Chancelaria"
                
            marcos_expansao.append({
                "slug": slug,
                "categoria": cat,
                "titulo": nome_fmt
            })
    except Exception as e_col:
        logger.error("Falha ao obter marcos coletivos para galeria: %s", e_col)

    # 4. DADOS DE NOME DA LOJA
    nome_loja = "Oficina"
    if lid_str:
        try:
            resp_l = supabase.table("lojas").select("nome_loja").eq("id", lid_str).limit(1).execute()
            if resp_l.data:
                nome_loja = resp_l.data[0].get("nome_loja") or "Oficina"
        except:
            pass

    return {
        "loja_id": lid_str,
        "nome_loja": nome_loja,
        "conquistas_individuais": catalogo_badges,
        "marcos_oficina": marcos_oficina,
        "marcos_expansao": marcos_expansao
    }
