# src/sheets.py
import gspread
import os
from datetime import datetime
import json

# Configuração do Google Sheets
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

# --- Funções para Membros ---
def buscar_membro(telegram_id: int):
    """Retorna o dicionário com dados do membro, incluindo as novas colunas."""
    try:
        ws = spreadsheet.worksheet("Membros")
        data = ws.get_all_records()
        for row in data:
            if row.get("Telegram ID") == telegram_id:
                # Garantir que Nivel seja string e tenha valor padrão "1"
                nivel = row.get("Nivel")
                if nivel is None or nivel == "":
                    nivel = "1"
                else:
                    # Converte número (ex: 3.0) para string sem decimal
                    nivel = str(int(float(nivel)))
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
            dados.get("telegram_id", ""),
            dados.get("nome", ""),
            dados.get("loja", ""),          # Nome da loja
            dados.get("grau", ""),
            dados.get("oriente", ""),
            dados.get("potencia", ""),
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            dados.get("cargo", ""),
            "1",                              # nível padrão
            dados.get("data_nasc", ""),       # coluna J
            dados.get("numero_loja", ""),     # coluna K
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
        cell = ws.find(str(telegram_id), in_column=1)  # coluna A
        if cell:
            ws.update_cell(cell.row, 9, novo_nivel)  # coluna I
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
            nivel = row.get("Nivel")
            if nivel is None or nivel == "":
                nivel = "1"
            else:
                nivel = str(int(float(nivel)))
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
        cell = ws.find(str(telegram_id), in_column=1)  # coluna A
        if not cell:
            print(f"Membro {telegram_id} não encontrado para atualização.")
            return False

        # Mapeamento atualizado com as novas colunas
        colunas = {
            "Nome": 2,
            "Loja": 3,
            "Grau": 4,
            "Oriente": 5,
            "Potência": 6,
            "Data de nascimento": 10,   # coluna J
            "Número da loja": 11,        # coluna K
            "Cargo": 8,
            "Nivel": 9,
        }
        # (Telefone foi removido)

        coluna = colunas.get(campo)
        if not coluna:
            print(f"Campo {campo} não mapeado para atualização.")
            return False

        ws.update_cell(cell.row, coluna, novo_valor)
        print(f"Membro {telegram_id} atualizado: {campo} = {novo_valor}")
        return True

    except Exception as e:
        print(f"Erro ao atualizar membro {telegram_id}: {e}")
        return False

# --- Funções para Eventos (inalteradas) ---
def listar_eventos():
    try:
        ws = spreadsheet.worksheet("Eventos")
        data = ws.get_all_records()
        eventos_ativos = [evento for evento in data if evento.get("Status") == "Ativo"]
        return eventos_ativos
    except Exception as e:
        print(f"Erro ao listar eventos: {e}")
        return []

def cadastrar_evento(dados: dict):
    try:
        ws = spreadsheet.worksheet("Eventos")
        row = [
            dados.get("data", ""),
            dados.get("dia_semana", ""),
            dados.get("hora", ""),
            dados.get("nome_loja", ""),
            dados.get("numero_loja", ""),
            dados.get("oriente", ""),
            dados.get("grau", ""),
            dados.get("tipo_sessao", ""),
            dados.get("rito", ""),
            dados.get("potencia", ""),
            dados.get("traje", ""),
            dados.get("agape", ""),
            dados.get("observacoes", ""),
            dados.get("telegram_id_grupo", ""),
            dados.get("telegram_id_secretario", ""),
            dados.get("status", "Ativo"),
            dados.get("endereco", ""),
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        print(f"Erro ao cadastrar evento: {e}")
        return False

# --- Funções para Confirmações (ATUALIZADAS com coluna Número da loja) ---
def registrar_confirmacao(dados: dict):
    """Registra uma confirmação de presença, incluindo número da loja."""
    try:
        ws = spreadsheet.worksheet("Confirmações")
        if buscar_confirmacao(dados["id_evento"], dados["telegram_id"]):
            return False

        # Ordem das colunas na aba Confirmações:
        # A: ID Evento, B: Telegram ID, C: Nome, D: Grau, E: Cargo, F: Loja,
        # G: Oriente, H: Potência, I: Ágape, J: Data e hora, K: Número da loja
        row = [
            dados.get("id_evento", ""),
            dados.get("telegram_id", ""),
            dados.get("nome", ""),
            dados.get("grau", ""),
            dados.get("cargo", ""),
            dados.get("loja", ""),
            dados.get("oriente", ""),
            dados.get("potencia", ""),
            dados.get("agape", ""),
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            dados.get("numero_loja", ""),  # NOVA coluna K
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        print(f"Erro ao registrar confirmação: {e}")
        return False

def buscar_confirmacao(id_evento: str, telegram_id: int):
    try:
        ws = spreadsheet.worksheet("Confirmações")
        data = ws.get_all_records()
        for row in data:
            if row.get("ID Evento") == id_evento and row.get("Telegram ID") == telegram_id:
                return row
        return None
    except Exception as e:
        print(f"Erro ao buscar confirmação: {e}")
        return None

def cancelar_confirmacao(id_evento: str, telegram_id: int):
    try:
        ws = spreadsheet.worksheet("Confirmações")
        cell_list = ws.findall(id_evento, in_column=1)
        for cell in cell_list:
            row_data = ws.row_values(cell.row)
            if len(row_data) > 1 and row_data[1] == str(telegram_id):
                ws.delete_rows(cell.row)
                return True
        return False
    except Exception as e:
        print(f"Erro ao cancelar confirmação: {e}")
        return False

def listar_confirmacoes_por_evento(id_evento: str):
    """Retorna lista de confirmações para um evento específico, incluindo número da loja."""
    try:
        ws = spreadsheet.worksheet("Confirmações")
        data = ws.get_all_records()
        confirmacoes = []
        for row in data:
            if row.get("ID Evento") == id_evento:
                confirmacoes.append(row)
        return confirmacoes
    except Exception as e:
        print(f"Erro ao listar confirmações: {e}")
        return []

def cancelar_todas_confirmacoes(id_evento: str):
    """Remove todas as confirmações de um evento."""
    try:
        ws = spreadsheet.worksheet("Confirmações")
        cell_list = ws.findall(id_evento, in_column=1)
        for cell in reversed(cell_list):
            ws.delete_rows(cell.row)
        return True
    except Exception as e:
        print(f"Erro ao cancelar confirmações: {e}")
        return False

# --- Funções para Eventos (continuação) ---
def atualizar_evento(indice: int, evento: dict):
    try:
        ws = spreadsheet.worksheet("Eventos")
        cell_list = ws.findall(evento.get("Data do evento", ""), in_column=1)
        for cell in cell_list:
            row_data = ws.row_values(cell.row)
            if row_data[3] == evento.get("Nome da loja"):
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
                        ws.update_cell(cell.row, coluna, valor)
                return True
        return False
    except Exception as e:
        print(f"Erro ao atualizar evento: {e}")
        return False