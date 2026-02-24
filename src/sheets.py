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
    """Retorna o dicionário com dados do membro, incluindo a coluna 'Nivel' como string "1","2","3"."""
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
    """Insere novo membro com nível padrão '1'."""
    try:
        ws = spreadsheet.worksheet("Membros")
        # Ordem das colunas: Telegram ID, Nome, Loja, Grau, Oriente, Potência, Data de cadastro, Cargo, Nivel
        row = [
            dados.get("telegram_id", ""),
            dados.get("nome", ""),
            dados.get("loja", ""),
            dados.get("grau", ""),
            dados.get("oriente", ""),
            dados.get("potencia", ""),
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            dados.get("cargo", ""),
            "1"  # nível padrão
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
        # Procura o telegram_id na coluna A (índice 1)
        cell = ws.find(str(telegram_id), in_column=1)
        if cell:
            # A coluna Nivel é a 9ª coluna (índice 9)
            ws.update_cell(cell.row, 9, novo_nivel)
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

# --- Funções para Eventos ---
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
        # A ordem aqui DEVE corresponder EXATAMENTE à ordem das colunas na sua planilha
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

# --- Funções para Confirmações ---
def registrar_confirmacao(dados: dict):
    try:
        ws = spreadsheet.worksheet("Confirmações")
        if buscar_confirmacao(dados["id_evento"], dados["telegram_id"]):
            return False

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
            datetime.now().strftime("%d/%m/%Y %H:%M:%S")
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
    """Retorna lista de confirmações para um evento específico."""
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