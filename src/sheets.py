# src/sheets.py
from __future__ import annotations

import os
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import gspread


# =========================
# Configuração do Google Sheets
# =========================
credentials_json_str = os.environ.get("GOOGLE_CREDENTIALS")
if credentials_json_str:
    try:
        credentials_dict = json.loads(credentials_json_str)
        gc = gspread.service_account_from_dict(credentials_dict)
    except json.JSONDecodeError as e:
        raise ValueError(f"Erro ao decodificar GOOGLE_CREDENTIALS como JSON: {e}")
else:
    raise ValueError("Variável de ambiente GOOGLE_CREDENTIALS não definida.")

spreadsheet = gc.open("Bode Andarilho")


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


def _headers(ws: gspread.Worksheet) -> List[str]:
    return [str(h).strip() for h in ws.row_values(1)]


def _header_map(ws: gspread.Worksheet) -> Dict[str, int]:
    """
    Retorna {Nome do cabeçalho -> índice 1-based}
    """
    hs = _headers(ws)
    out: Dict[str, int] = {}
    for idx, h in enumerate(hs, start=1):
        if h:
            out[h] = idx
    return out


def _col_index(ws: gspread.Worksheet, header_name: str) -> int:
    """
    Retorna o índice (1-based) da coluna pelo nome do cabeçalho.
    Lança ValueError se não encontrar.
    """
    hmap = _header_map(ws)
    if header_name in hmap:
        return hmap[header_name]
    raise ValueError(f"Cabeçalho '{header_name}' não encontrado na aba '{ws.title}'.")


def _append_row_by_headers(ws: gspread.Worksheet, values_by_header: Dict[str, Any]) -> bool:
    """
    Append respeitando a ordem do cabeçalho.
    Se o cabeçalho não existir, ignora aquela chave.
    """
    try:
        hs = _headers(ws)
        if not hs:
            return False

        row_out = [""] * len(hs)
        hmap = _header_map(ws)

        for header, value in values_by_header.items():
            if header in hmap:
                row_out[hmap[header] - 1] = _norm_text(value)

        ws.append_row(row_out, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


def _update_row_by_headers(ws: gspread.Worksheet, row_index: int, values_by_header: Dict[str, Any]) -> bool:
    """
    Atualiza células da linha via cabeçalho (não depende de posição fixa).
    """
    try:
        hmap = _header_map(ws)
        cells: List[gspread.Cell] = []
        for header, value in values_by_header.items():
            if header in hmap:
                cells.append(gspread.Cell(row_index, hmap[header], _norm_text(value)))
        if not cells:
            return True
        ws.update_cells(cells, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


def gerar_id_evento() -> str:
    """Gera um ID único e estável para o evento."""
    return uuid.uuid4().hex  # 32 chars


def _find_row_by_exact_value(ws: gspread.Worksheet, header: str, exact_value: str) -> Optional[int]:
    """
    Procura a primeira linha onde a célula da coluna 'header' é exatamente 'exact_value'.
    Retorna o número da linha (1-based) ou None.
    """
    try:
        col = _col_index(ws, header)
        target = _norm_text(exact_value)
        if not target:
            return None

        matches = ws.findall(target, in_column=col)
        for m in matches:
            if _norm_text(ws.cell(m.row, col).value) == target:
                return m.row
        return None
    except Exception:
        return None


# =========================
# Funções para Membros
# =========================
def listar_membros() -> List[Dict[str, Any]]:
    """Retorna lista de todos os membros cadastrados."""
    try:
        ws = spreadsheet.worksheet("Membros")
        return ws.get_all_records()
    except Exception as e:
        print(f"Erro ao listar membros: {e}")
        return []


def buscar_membro(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Retorna o dicionário com dados do membro."""
    try:
        ws = spreadsheet.worksheet("Membros")
        data = ws.get_all_records()

        target_id = _norm_intlike(telegram_id)
        for row in data:
            row_id = _norm_intlike(row.get("Telegram ID"))
            if row_id and row_id == target_id:
                # Garantir que Nivel seja string e tenha valor padrão "1"
                nivel = row.get("Nivel")
                nivel = _norm_intlike(nivel) or "1"
                row["Nivel"] = nivel
                return row

        return None
    except Exception as e:
        print(f"Erro ao buscar membro: {e}")
        return None


def cadastrar_membro(dados: dict) -> bool:
    """
    Insere novo membro.
    - Se já existir (Telegram ID), atualiza dados mantendo Nivel.
    - Nivel padrão: "1".
    - Escreve por cabeçalho quando possível (não quebra ao adicionar coluna).
    """
    try:
        ws = spreadsheet.worksheet("Membros")
        hmap = _header_map(ws)

        telegram_id = _norm_intlike(dados.get("Telegram ID") or dados.get("telegram_id"))
        if not telegram_id:
            return False

        # Se existe: atualiza (preserva Nivel)
        row_index = _find_row_by_exact_value(ws, "Telegram ID", telegram_id)
        if row_index:
            return atualizar_membro(int(float(telegram_id)), dados, preservar_nivel=True)

        # Se não existe: append com Nivel default
        values: Dict[str, Any] = {}

        def put(header: str, value: Any):
            if header in hmap:
                values[header] = value

        # Campos comuns (só escreve se a coluna existir)
        put("Telegram ID", telegram_id)
        put("Nome", dados.get("Nome") or dados.get("nome"))
        put("Grau", dados.get("Grau") or dados.get("grau"))
        put("Cargo", dados.get("Cargo") or dados.get("cargo"))
        put("Loja", dados.get("Loja") or dados.get("loja"))
        put("Número da loja", dados.get("Número da loja") or dados.get("numero_loja"))
        put("Oriente", dados.get("Oriente") or dados.get("oriente"))
        put("Potência", dados.get("Potência") or dados.get("potencia"))
        put("Data de nascimento", dados.get("Data de nascimento") or dados.get("data_nasc") or dados.get("nascimento"))
        put("Venerável Mestre", dados.get("Venerável Mestre") or dados.get("veneravel_mestre") or dados.get("vm"))

        # Nivel default
        put("Nivel", _norm_intlike(dados.get("Nivel")) or "1")

        ok = _append_row_by_headers(ws, values)
        return ok

    except Exception as e:
        print(f"Erro ao cadastrar membro: {e}")
        return False


def atualizar_membro(telegram_id: int, dados_atualizados: dict, preservar_nivel: bool = True) -> bool:
    """
    Atualiza um membro existente pelo Telegram ID.
    - preservar_nivel=True impede sobrescrever Nivel por acidente.
    """
    try:
        ws = spreadsheet.worksheet("Membros")
        telegram_id_norm = _norm_intlike(telegram_id)
        if not telegram_id_norm:
            return False

        row_index = _find_row_by_exact_value(ws, "Telegram ID", telegram_id_norm)
        if not row_index:
            return False

        # Preservar Nivel lendo do registro atual, se necessário
        if preservar_nivel:
            try:
                data = ws.get_all_records()
                atual = None
                for r in data:
                    if _norm_intlike(r.get("Telegram ID")) == telegram_id_norm:
                        atual = r
                        break
                if atual is not None:
                    nivel_atual = _norm_intlike(atual.get("Nivel")) or "1"
                else:
                    nivel_atual = "1"
            except Exception:
                nivel_atual = "1"
        else:
            nivel_atual = None

        hmap = _header_map(ws)
        values: Dict[str, Any] = {}

        def put(header: str, value: Any):
            if header in hmap:
                values[header] = value

        # Atualiza somente o que vier no dict (por cabeçalho)
        for k, v in dados_atualizados.items():
            # Aceita chaves no mesmo nome do cabeçalho
            if k in hmap:
                values[k] = v

        # Também aceita aliases usados no seu bot
        if "Nome" in hmap and ("nome" in dados_atualizados) and ("Nome" not in values):
            values["Nome"] = dados_atualizados.get("nome")
        if "Grau" in hmap and ("grau" in dados_atualizados) and ("Grau" not in values):
            values["Grau"] = dados_atualizados.get("grau")
        if "Cargo" in hmap and ("cargo" in dados_atualizados) and ("Cargo" not in values):
            values["Cargo"] = dados_atualizados.get("cargo")
        if "Loja" in hmap and ("loja" in dados_atualizados) and ("Loja" not in values):
            values["Loja"] = dados_atualizados.get("loja")
        if "Número da loja" in hmap and ("numero_loja" in dados_atualizados) and ("Número da loja" not in values):
            values["Número da loja"] = dados_atualizados.get("numero_loja")
        if "Oriente" in hmap and ("oriente" in dados_atualizados) and ("Oriente" not in values):
            values["Oriente"] = dados_atualizados.get("oriente")
        if "Potência" in hmap and ("potencia" in dados_atualizados) and ("Potência" not in values):
            values["Potência"] = dados_atualizados.get("potencia")
        if "Data de nascimento" in hmap and ("data_nasc" in dados_atualizados) and ("Data de nascimento" not in values):
            values["Data de nascimento"] = dados_atualizados.get("data_nasc")
        if "Venerável Mestre" in hmap and ("vm" in dados_atualizados or "veneravel_mestre" in dados_atualizados) and ("Venerável Mestre" not in values):
            values["Venerável Mestre"] = dados_atualizados.get("vm") or dados_atualizados.get("veneravel_mestre")

        # Reaplica Nivel atual se preservar_nivel
        if preservar_nivel and "Nivel" in hmap:
            values["Nivel"] = nivel_atual

        ok = _update_row_by_headers(ws, row_index, values)
        return ok

    except Exception as e:
        print(f"Erro ao atualizar membro: {e}")
        return False


def atualizar_nivel_membro(telegram_id: int, novo_nivel: str) -> bool:
    """
    Atualiza somente o Nivel (uso admin).
    """
    try:
        ws = spreadsheet.worksheet("Membros")
        telegram_id_norm = _norm_intlike(telegram_id)
        if not telegram_id_norm:
            return False

        row_index = _find_row_by_exact_value(ws, "Telegram ID", telegram_id_norm)
        if not row_index:
            return False

        hmap = _header_map(ws)
        if "Nivel" not in hmap:
            return False

        return _update_row_by_headers(ws, row_index, {"Nivel": _norm_intlike(novo_nivel) or "1"})
    except Exception as e:
        print(f"Erro ao atualizar nível: {e}")
        return False


# =========================
# Funções para Eventos
# =========================
def listar_eventos(include_inativos: bool = False) -> List[dict]:
    """
    Lista eventos. Por padrão retorna apenas status 'ativo' (ou vazio => ativo).
    """
    try:
        ws = spreadsheet.worksheet("Eventos")
        data = ws.get_all_records()

        if include_inativos:
            return data

        ativos: List[dict] = []
        for row in data:
            status = _norm_status(row.get("Status"))
            if status in ("ativo",):
                ativos.append(row)
        return ativos

    except Exception as e:
        print(f"Erro ao listar eventos: {e}")
        return []


def cadastrar_evento(evento: dict) -> Optional[str]:
    """
    Insere um novo evento. Se existir coluna 'ID Evento', garante preenchimento.
    Retorna o ID Evento (ou None em erro).
    """
    try:
        ws = spreadsheet.worksheet("Eventos")
        hmap = _header_map(ws)

        # Garante ID Evento se a coluna existir
        id_evento = _norm_text(evento.get("ID Evento") or evento.get("id_evento"))
        if "ID Evento" in hmap and not id_evento:
            id_evento = gerar_id_evento()
            evento = dict(evento)
            evento["ID Evento"] = id_evento

        ok = _append_row_by_headers(ws, evento)
        return id_evento if ok else None

    except Exception as e:
        print(f"Erro ao cadastrar evento: {e}")
        return None


def atualizar_evento(indice: int, evento: dict) -> bool:
    """
    Mantido por compatibilidade com o fluxo atual.

    Melhorias:
    - Se existir coluna 'ID Evento' e vier preenchido, atualiza por ID (não ambíguo).
    - Caso contrário, mantém fallback legado: busca por Data do evento (col 1) + Nome da loja (col 4).
    """
    try:
        ws = spreadsheet.worksheet("Eventos")
        hmap = _header_map(ws)

        # 1) Preferência: atualizar por ID Evento (se possível)
        if "ID Evento" in hmap:
            id_evento = _norm_text(evento.get("ID Evento"))
            if id_evento:
                row_idx = _find_row_by_exact_value(ws, "ID Evento", id_evento)
                if row_idx:
                    return _update_row_by_headers(ws, row_idx, evento)

        # 2) Fallback legado (como você tinha)
        data_ev = _norm_text(evento.get("Data do evento", ""))
        nome_loja = _norm_text(evento.get("Nome da loja", ""))

        if not data_ev or not nome_loja:
            return False

        # Colunas legadas fixas (compatibilidade total)
        cell_list = ws.findall(data_ev, in_column=1)
        for cell in cell_list:
            row_data = ws.row_values(cell.row)
            # Coluna 4 (1-based) => índice 3 (0-based)
            if len(row_data) >= 4 and _norm_text(row_data[3]) == nome_loja:
                # Se possível, atualiza por cabeçalho (robusto)
                if hmap:
                    return _update_row_by_headers(ws, cell.row, evento)

                # Se não houver cabeçalho (muito raro), usa o mapeamento fixo antigo
                mapeamento = {
                    "Data do evento": 1,
                    "Dia da semana": 2,
                    "Hora": 3,
                    "Nome da loja": 4,
                    "Número da loja": 5,
                    "Oriente": 6,
                    "Grau": 7,
                    "Tipo de sessão": 8,
                    "Rito": 9,
                    "Potência": 10,
                    "Traje obrigatório": 11,
                    "Ágape": 12,
                    "Observações": 13,
                    "Telegram ID do grupo": 14,
                    "Telegram ID do secretário": 15,
                    "Status": 16,
                    "Endereço da sessão": 17,
                }
                for chave, valor in evento.items():
                    coluna = mapeamento.get(chave)
                    if coluna:
                        ws.update_cell(cell.row, coluna, _norm_text(valor))
                return True

        return False

    except Exception as e:
        print(f"Erro ao atualizar evento: {e}")
        return False


# =========================
# Funções para Confirmações
# =========================
def registrar_confirmacao(dados: dict) -> bool:
    """
    Registra confirmação na aba Confirmações.
    Evita duplicar confirmação do mesmo Telegram ID para o mesmo ID Evento.
    """
    try:
        ws = spreadsheet.worksheet("Confirmações")
        hmap = _header_map(ws)

        id_evento = _norm_text(dados.get("id_evento") or dados.get("ID Evento"))
        telegram_id = _norm_intlike(dados.get("telegram_id") or dados.get("Telegram ID"))

        if not id_evento or not telegram_id:
            return False

        # evita duplicidade
        if buscar_confirmacao(id_evento, int(float(telegram_id))):
            return False

        values: Dict[str, Any] = {}

        def put(header: str, value: Any):
            if header in hmap:
                values[header] = value

        put("ID Evento", id_evento)
        put("Telegram ID", telegram_id)
        put("Nome", dados.get("nome") or dados.get("Nome"))
        put("Grau", dados.get("grau") or dados.get("Grau"))
        put("Cargo", dados.get("cargo") or dados.get("Cargo"))
        put("Loja", dados.get("loja") or dados.get("Loja"))
        put("Número da loja", dados.get("numero_loja") or dados.get("Número da loja"))
        put("Oriente", dados.get("oriente") or dados.get("Oriente"))
        put("Potência", dados.get("potencia") or dados.get("Potência"))
        put("Ágape", dados.get("agape") or dados.get("Ágape"))
        put("Data e hora", _now_str(segundos=True))

        # Opcional: grava se existir a coluna na aba Confirmações
        if "Venerável Mestre" in hmap:
            put("Venerável Mestre", dados.get("veneravel_mestre") or dados.get("Venerável Mestre") or dados.get("vm"))

        ok = _append_row_by_headers(ws, values)
        return ok

    except Exception as e:
        print(f"Erro ao registrar confirmação: {e}")
        return False


def buscar_confirmacao(id_evento: str, telegram_id: int) -> Optional[dict]:
    """Verifica se um usuário já confirmou em determinado evento."""
    try:
        ws = spreadsheet.worksheet("Confirmações")
        data = ws.get_all_records()

        target_evento = _norm_text(id_evento)
        target_id = _norm_intlike(telegram_id)

        for row in data:
            row_evento = _norm_text(row.get("ID Evento"))
            row_tid = _norm_intlike(row.get("Telegram ID"))
            if row_evento == target_evento and row_tid == target_id:
                return row
        return None

    except Exception as e:
        print(f"Erro ao buscar confirmação: {e}")
        return None


def cancelar_confirmacao(id_evento: str, telegram_id: int) -> bool:
    """Remove a confirmação do usuário no evento (delete da linha)."""
    try:
        ws = spreadsheet.worksheet("Confirmações")

        target_evento = _norm_text(id_evento)
        target_id = _norm_intlike(telegram_id)
        if not target_evento or not target_id:
            return False

        col_evento = _col_index(ws, "ID Evento")
        col_tid = _col_index(ws, "Telegram ID")

        cell_list = ws.findall(target_evento, in_column=col_evento)
        for cell in cell_list:
            if _norm_text(ws.cell(cell.row, col_evento).value) != target_evento:
                continue
            if _norm_intlike(ws.cell(cell.row, col_tid).value) == target_id:
                ws.delete_rows(cell.row)
                return True

        return False

    except Exception as e:
        print(f"Erro ao cancelar confirmação: {e}")
        return False


def listar_confirmacoes_por_evento(id_evento: str) -> List[dict]:
    """Retorna lista de confirmações para um evento específico."""
    try:
        ws = spreadsheet.worksheet("Confirmações")
        data = ws.get_all_records()

        target_evento = _norm_text(id_evento)
        confirmacoes = []
        for row in data:
            if _norm_text(row.get("ID Evento")) == target_evento:
                confirmacoes.append(row)
        return confirmacoes

    except Exception as e:
        print(f"Erro ao listar confirmações: {e}")
        return []


def cancelar_todas_confirmacoes(id_evento: str) -> bool:
    """Remove todas as confirmações de um evento."""
    try:
        ws = spreadsheet.worksheet("Confirmações")

        target_evento = _norm_text(id_evento)
        if not target_evento:
            return False

        col_evento = _col_index(ws, "ID Evento")
        cell_list = ws.findall(target_evento, in_column=col_evento)

        # Apaga de baixo para cima para não deslocar índices
        for cell in reversed(cell_list):
            if _norm_text(ws.cell(cell.row, col_evento).value) == target_evento:
                ws.delete_rows(cell.row)
        return True

    except Exception as e:
        print(f"Erro ao cancelar confirmações: {e}")
        return False
# =========================
# Funções para Notificações (coluna M)
# =========================
def get_notificacao_status(telegram_id: int) -> bool:
    """
    Retorna True se o usuário tem notificações ativas (coluna "Notificações" = "SIM")
    Retorna False caso contrário.
    """
    try:
        membro = buscar_membro(telegram_id)
        if not membro:
            return False
        notificacao = str(membro.get("Notificações", "") or "").strip().upper()
        return notificacao == "SIM"
    except Exception as e:
        print(f"Erro ao buscar status de notificação: {e}")
        return False


def set_notificacao_status(telegram_id: int, ativo: bool) -> bool:
    """
    Atualiza a coluna "Notificações" para "SIM" (True) ou "NÃO" (False).
    Retorna True se sucesso.
    """
    try:
        from src.sheets import atualizar_membro
        valor = "SIM" if ativo else "NÃO"
        return atualizar_membro(telegram_id, {"Notificações": valor}, preservar_nivel=True)
    except Exception as e:
        print(f"Erro ao atualizar status de notificação: {e}")
        return False