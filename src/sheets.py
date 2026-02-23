import gspread
from google.oauth2.service_account import Credentials
import os
import json

def conectar_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credenciais_json = os.getenv("GOOGLE_CREDENTIALS")
    credenciais_dict = json.loads(credenciais_json)
    creds = Credentials.from_service_account_info(credenciais_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet_id = os.getenv("SHEET_ID")
    return client.open_by_key(sheet_id)


def buscar_membro(telegram_id: int):
    sheet = conectar_sheets()
    aba = sheet.worksheet("Membros")
    registros = aba.get_all_records()

    for registro in registros:
        if str(registro.get("Telegram ID", "")) == str(telegram_id):
            return registro
    return None


def cadastrar_membro(dados: dict):
    sheet = conectar_sheets()
    aba = sheet.worksheet("Membros")

    linha = [
        dados.get("nome", ""),
        dados.get("loja", ""),
        dados.get("grau", ""),
        dados.get("oriente", ""),
        dados.get("potencia", ""),
        dados.get("telefone", ""),
        dados.get("telegram_id", ""),
        dados.get("nivel", "membro"),
    ]

    aba.append_row(linha)


def cadastrar_evento(dados: dict):
    sheet = conectar_sheets()
    aba = sheet.worksheet("Eventos")

    linha = [
        dados.get("data", ""),
        dados.get("dia_semana", ""),
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

    aba.append_row(linha)
