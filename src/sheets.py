# src/sheets.py
import os
import json
import uuid
from datetime import datetime

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


def _norm_intlike(value) -> str:
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
        # "123.0" -> "123"
        try:
            fv = float(v)
            if fv.is_integer():
                return str(int(fv))
        except Exception:
            pass
        return v

    # número
    try:
        fv = float(value)
        if fv.is_integer():
            return str(int(fv))
        return str(value)
    except Exception:
        return str(value)


def _norm_text(value) -> str:
    if value is None:
        return ""
    v = str(value).strip()
    return "" if v.lower() == "nan" else v


def _norm_status(value) -> str:
    """
    Normaliza status para comparação.
    Regra: vazio/None => "ativo" (retrocompatível)
    """
    v = _norm_text(value).lower()
    return v if v else "ativo"


def _col_index(ws: gspread.Worksheet, header_name: str) -> int:
    """
    Retorna o índice (1-based) da coluna pelo nome do cabeçalho.
    Lança ValueError se não encontrar.
    """
    headers = ws.row_values(1)
    for i, h in enumerate(headers, start=1):
        if str(h).strip() == header_name:
            return i
    raise ValueError(f"Cabeçalho '{header_name}' não encontrado na aba '{ws.title}'.")


def gerar_id_evento() -> str:
    """Gera um ID único e estável para o evento."""
    return uuid.uuid4().hex  # 32 chars, colisão praticamente impossível


# =========================
# Funções para Membros
# =========================
def buscar_membro(telegram_id: int):
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


def cadastrar_membro(dados: dict):
    """Insere novo membro com nível padrão '1', incluindo data de nascimento e número da loja."""
    try:
        ws = spreadsheet.worksheet("Membros")
        # Ordem das colunas:
        # A: Telegram ID, B: Nome, C: Loja, D: Grau, E: Oriente, F: Potência,
        # G: Data de cadastro, H: Cargo, I: Nivel, J: Data de nascimento, K: Número da loja
        row = [
            _norm_intlike(dados.get("telegram_id", "")),
            _norm_text(dados.get("nome", "")),
            _norm_text(dados.get("loja", "")),  # Nome da loja
            _norm_text(dados.get("grau", "")),
            _norm_text(dados.get("oriente", "")),
            _norm_text(dados.get("potencia", "")),
            _now_str(segundos=False),
            _norm_text(dados.get("cargo", "")),
            "1",  # nível padrão
            _norm_text(dados.get("data_nasc", "")),  # coluna J
            _norm_text(dados.get("numero_loja", "")),  # coluna K
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        print(f"Erro ao cadastrar membro: {e}")
        return False


def atualizar_nivel(telegram_id: int, novo_nivel: str):
    """Atualiza o nível de um membro. Retorna True se bem-sucedido."""
    try:
        ws = spreadsheet.worksheet("Membros")
        cell = ws.find(_norm_intlike(telegram_id), in_column=1)  # coluna A
        if cell:
            ws.update_cell(cell.row, 9, _norm_intlike(novo_nivel) or "1")  # coluna I
            return True
        return False
    except Exception as e:
        print(f"Erro ao atualizar nível: {e}")
        return False


def listar_membros():
    """Retorna lista de todos os membros cadastrados, com nível tratado."""
    try:
        ws = spreadsheet.worksheet("Membros")
        data = ws.get_all_records()
        membros = []
        for row in data:
            nivel = _norm_intlike(row.get("Nivel")) or "1"
            row["Nivel"] = nivel
            membros.append(row)
        return membros
    except Exception as e:
        print(f"Erro ao listar membros: {e}")
        return []


def atualizar_membro(telegram_id: int, campo: str, novo_valor: str):
    """
    Atualiza um campo específico de um membro na planilha.
    Retorna True se bem-sucedido, False caso contrário.
    """
    try:
        ws = spreadsheet.worksheet("Membros")
        cell = ws.find(_norm_intlike(telegram_id), in_column=1)  # coluna A
        if not cell:
            print(f"Membro {telegram_id} não encontrado para atualização.")
            return False

        # Mapeamento (mantido por compatibilidade com a planilha atual)
        colunas = {
            "Nome": 2,
            "Loja": 3,
            "Grau": 4,
            "Oriente": 5,
            "Potência": 6,
            "Data de nascimento": 10,  # coluna J
            "Número da loja": 11,  # coluna K
            "Cargo": 8,
            "Nivel": 9,
        }

        coluna = colunas.get(campo)
        if not coluna:
            print(f"Campo {campo} não mapeado para atualização.")
            return False

        ws.update_cell(cell.row, coluna, _norm_text(novo_valor))
        print(f"Membro {telegram_id} atualizado: {campo} = {novo_valor}")
        return True

    except Exception as e:
        print(f"Erro ao atualizar membro {telegram_id}: {e}")
        return False


# =========================
# Funções para Eventos
# (compatível com planilha v2: ID Evento + auditoria de cancelamento)
# =========================
def listar_eventos():
    """
    Retorna eventos ativos.
    Regra: Status vazio conta como Ativo (retrocompatível).
    """
    try:
        ws = spreadsheet.worksheet("Eventos")
        data = ws.get_all_records()
        eventos_ativos = []
        for evento in data:
            status_norm = _norm_status(evento.get("Status"))
            if status_norm == "ativo":
                eventos_ativos.append(evento)
        return eventos_ativos
    except Exception as e:
        print(f"Erro ao listar eventos: {e}")
        return []


def buscar_evento_por_id(id_evento: str):
    """Busca um evento pelo 'ID Evento' na aba Eventos."""
    try:
        ws = spreadsheet.worksheet("Eventos")
        data = ws.get_all_records()
        target = _norm_text(id_evento)
        if not target:
            return None

        for row in data:
            rid = _norm_text(row.get("ID Evento"))
            if rid and rid == target:
                return row
        return None
    except Exception as e:
        print(f"Erro ao buscar evento por ID: {e}")
        return None


def cadastrar_evento(dados: dict):
    """
    Cadastra evento na aba Eventos (planilha v2).
    Retorno:
      - str (ID Evento) em caso de sucesso
      - None em caso de falha
    """
    try:
        ws = spreadsheet.worksheet("Eventos")

        id_evento = gerar_id_evento()

        # Status padronizado
        status_raw = dados.get("Status", None)
        if status_raw is None:
            status_raw = dados.get("status", None)
        status_val = "Ativo" if _norm_status(status_raw) == "ativo" else _norm_text(status_raw) or "Ativo"

        # Ordem das colunas (v2):
        # 1..17 (originais) + 18 ID Evento + 19 Cancelado em + 20 Cancelado por (Telegram ID) + 21 Cancelado por (Nome)
        row = [
            _norm_text(dados.get("data", "")),
            _norm_text(dados.get("dia_semana", "")),
            _norm_text(dados.get("hora", "")),
            _norm_text(dados.get("nome_loja", "")),
            _norm_text(dados.get("numero_loja", "")),
            _norm_text(dados.get("oriente", "")),
            _norm_text(dados.get("grau", "")),
            _norm_text(dados.get("tipo_sessao", "")),
            _norm_text(dados.get("rito", "")),
            _norm_text(dados.get("potencia", "")),
            _norm_text(dados.get("traje", "")),
            _norm_text(dados.get("agape", "")),
            _norm_text(dados.get("observacoes", "")),
            _norm_intlike(dados.get("telegram_id_grupo", "")),
            _norm_intlike(dados.get("telegram_id_secretario", "")),
            status_val,
            _norm_text(dados.get("endereco", "")),
            id_evento,  # ID Evento
            "",  # Cancelado em
            "",  # Cancelado por (Telegram ID)
            "",  # Cancelado por (Nome)
        ]

        ws.append_row(row)
        return id_evento

    except Exception as e:
        print(f"Erro ao cadastrar evento: {e}")
        return None


def cancelar_evento(id_evento: str, cancelado_por_telegram_id: int, cancelado_por_nome: str):
    """
    Cancela (não exclui) um evento, preenchendo auditoria.
    Atualiza na aba Eventos:
      - Status = Cancelado
      - Cancelado em = agora
      - Cancelado por (Telegram ID)
      - Cancelado por (Nome)
    Retorna True/False.
    """
    try:
        ws = spreadsheet.worksheet("Eventos")
        target_id = _norm_text(id_evento)
        if not target_id:
            return False

        # Descobre índices por cabeçalho (mais robusto que hardcode)
        col_id = _col_index(ws, "ID Evento")
        col_status = _col_index(ws, "Status")
        col_cancelado_em = _col_index(ws, "Cancelado em")
        col_cancelado_por_id = _col_index(ws, "Cancelado por (Telegram ID)")
        col_cancelado_por_nome = _col_index(ws, "Cancelado por (Nome)")

        cell = ws.find(target_id, in_column=col_id)
        if not cell:
            return False

        # Garantia de igualdade exata
        if _norm_text(ws.cell(cell.row, col_id).value) != target_id:
            return False

        ts = _now_str(segundos=True)
        canc_id = _norm_intlike(cancelado_por_telegram_id)
        canc_nome = _norm_text(cancelado_por_nome)

        ws.update_cells(
            [
                gspread.Cell(cell.row, col_status, "Cancelado"),
                gspread.Cell(cell.row, col_cancelado_em, ts),
                gspread.Cell(cell.row, col_cancelado_por_id, canc_id),
                gspread.Cell(cell.row, col_cancelado_por_nome, canc_nome),
            ]
        )
        return True

    except Exception as e:
        print(f"Erro ao cancelar evento: {e}")
        return False


# =========================
# Funções para Confirmações
# =========================
def registrar_confirmacao(dados: dict):
    """Registra uma confirmação de presença."""
    try:
        ws = spreadsheet.worksheet("Confirmações")

        id_evento = _norm_text(dados.get("id_evento", ""))
        telegram_id = _norm_intlike(dados.get("telegram_id", ""))

        if not id_evento or not telegram_id:
            return False

        if buscar_confirmacao(id_evento, telegram_id):
            return False

        # Ordem das colunas na aba Confirmações:
        # A: ID Evento, B: Telegram ID, C: Nome, D: Grau, E: Cargo, F: Loja,
        # G: Oriente, H: Potência, I: Ágape, J: Data e hora, K: Número da loja
        row = [
            id_evento,
            telegram_id,
            _norm_text(dados.get("nome", "")),
            _norm_text(dados.get("grau", "")),
            _norm_text(dados.get("cargo", "")),
            _norm_text(dados.get("loja", "")),
            _norm_text(dados.get("oriente", "")),
            _norm_text(dados.get("potencia", "")),
            _norm_text(dados.get("agape", "")),
            _now_str(segundos=True),
            _norm_text(dados.get("numero_loja", "")),
        ]
        ws.append_row(row)
        return True

    except Exception as e:
        print(f"Erro ao registrar confirmação: {e}")
        return False


def buscar_confirmacao(id_evento: str, telegram_id: int):
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


def cancelar_confirmacao(id_evento: str, telegram_id: int):
    """Remove a confirmação do usuário no evento (delete da linha)."""
    try:
        ws = spreadsheet.worksheet("Confirmações")

        target_evento = _norm_text(id_evento)
        target_id = _norm_intlike(telegram_id)
        if not target_evento or not target_id:
            return False

        # Busca candidatos por evento
        cell_list = ws.findall(target_evento, in_column=1)
        for cell in cell_list:
            # Confere igualdade exata do ID Evento na coluna A
            if _norm_text(ws.cell(cell.row, 1).value) != target_evento:
                continue

            row_data = ws.row_values(cell.row)
            # Coluna B = Telegram ID
            if len(row_data) > 1 and _norm_intlike(row_data[1]) == target_id:
                ws.delete_rows(cell.row)
                return True

        return False

    except Exception as e:
        print(f"Erro ao cancelar confirmação: {e}")
        return False


def listar_confirmacoes_por_evento(id_evento: str):
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


def cancelar_todas_confirmacoes(id_evento: str):
    """Remove todas as confirmações de um evento."""
    try:
        ws = spreadsheet.worksheet("Confirmações")

        target_evento = _norm_text(id_evento)
        if not target_evento:
            return False

        cell_list = ws.findall(target_evento, in_column=1)

        # Apaga de baixo para cima para não deslocar índices
        for cell in reversed(cell_list):
            if _norm_text(ws.cell(cell.row, 1).value) == target_evento:
                ws.delete_rows(cell.row)
        return True

    except Exception as e:
        print(f"Erro ao cancelar confirmações: {e}")
        return False


# =========================
# Funções para Eventos (continuação)
# =========================
def atualizar_evento(indice: int, evento: dict):
    """
    Mantido por compatibilidade com o fluxo atual.
    Observação: este método ainda procura por Data + Nome da loja e pode ser ambíguo
    se houver eventos duplicados.
    """
    try:
        ws = spreadsheet.worksheet("Eventos")
        cell_list = ws.findall(evento.get("Data do evento", ""), in_column=1)
        for cell in cell_list:
            row_data = ws.row_values(cell.row)
            if len(row_data) >= 4 and row_data[3] == evento.get("Nome da loja"):
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