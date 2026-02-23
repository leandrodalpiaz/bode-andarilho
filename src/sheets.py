import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def conectar_planilha():
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    cliente = gspread.authorize(creds)
    planilha = cliente.open("Bode Andarilho")
    return planilha

def listar_eventos():
    planilha = conectar_planilha()
    aba = planilha.worksheet("Eventos")
    registros = aba.get_all_records()
    return [e for e in registros if str(e.get("Status", "")).lower() == "ativo"]

def buscar_evento_por_indice(indice):
    eventos = listar_eventos()
    if 0 <= indice < len(eventos):
        return eventos[indice]
    return None

def registrar_confirmacao(dados: dict):
    planilha = conectar_planilha()
    aba = planilha.worksheet("Confirmações")
    nova_linha = [
        dados.get("id_evento", ""),
        dados.get("telegram_id", ""),
        dados.get("nome", ""),
        dados.get("grau", ""),
        dados.get("cargo", ""),
        dados.get("loja", ""),
        dados.get("oriente", ""),
        dados.get("potencia", ""),
        dados.get("agape", ""),
        datetime.now().strftime("%d/%m/%Y %H:%M")
    ]
    aba.append_row(nova_linha)

def listar_confirmacoes(id_evento: str):
    planilha = conectar_planilha()
    aba = planilha.worksheet("Confirmações")
    valores = aba.get_all_values()
    resultado = []
    for linha in valores[1:]:
        if len(linha) >= 2 and str(linha[0]) == str(id_evento):
            resultado.append({
                "ID Evento": linha[0],
                "Telegram ID": linha[1],
                "Nome": linha[2] if len(linha) > 2 else ""
            })
    return resultado

def buscar_confirmacao(id_evento: str, telegram_id):
    planilha = conectar_planilha()
    aba = planilha.worksheet("Confirmações")
    valores = aba.get_all_values()
    for linha in valores[1:]:
        if len(linha) >= 2:
            if str(linha[0]).strip() == str(id_evento).strip() and str(linha[1]).strip() == str(telegram_id).strip():
                return True
    return False

def cancelar_confirmacao(id_evento: str, telegram_id):
    planilha = conectar_planilha()
    aba = planilha.worksheet("Confirmações")
    valores = aba.get_all_values()
    for i, linha in enumerate(valores):
        if i == 0:
            continue
        if len(linha) >= 2:
            if str(linha[0]).strip() == str(id_evento).strip() and str(linha[1]).strip() == str(telegram_id).strip():
                aba.delete_rows(i + 1)
                return True
    return False

def buscar_membro(telegram_id):
    planilha = conectar_planilha()
    aba = planilha.worksheet("Membros")
    registros = aba.get_all_records()
    for membro in registros:
        if str(membro.get("Telegram ID", "")) == str(telegram_id):
            return membro
    return None

def cadastrar_membro(dados: dict):
    planilha = conectar_planilha()
    aba = planilha.worksheet("Membros")
    nova_linha = [
        dados.get("telegram_id", ""),
        dados.get("nome", ""),
        dados.get("loja", ""),
        dados.get("grau", ""),
        dados.get("oriente", ""),
        dados.get("potencia", ""),
        datetime.now().strftime("%d/%m/%Y %H:%M")
    ]
    aba.append_row(nova_linha)
