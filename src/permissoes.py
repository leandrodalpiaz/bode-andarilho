# src/permissoes.py
from src.sheets import get_nivel_membro
import os

def get_nivel(telegram_id: int):
    # Verifica se é o ADMIN_TELEGRAM_ID do ambiente
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id and str(telegram_id) == admin_id:
        return "admin"

    # Busca o nível na planilha de membros
    return get_nivel_membro(telegram_id)
