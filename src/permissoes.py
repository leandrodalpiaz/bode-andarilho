# src/permissoes.py
from src.sheets import buscar_membro
import os

def get_nivel(telegram_id: int) -> str:
    """
    Retorna o nível de acesso do usuário como string:
    "1" = comum
    "2" = secretário
    "3" = admin
    """
    # 1. Admin definido por variável de ambiente tem nível 3
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id and str(telegram_id) == admin_id:
        return "3"

    # 2. Busca o membro na planilha (já tratado para retornar "1","2","3")
    membro = buscar_membro(telegram_id)
    if membro:
        return membro.get("Nivel", "1")
    return "1"  # visitante ou não cadastrado