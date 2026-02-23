import os
from src.sheets import buscar_membro

ADMIN_ID = os.getenv("ADMIN_TELEGRAM_ID", "")

def is_admin(telegram_id: int) -> bool:
    return str(telegram_id) == str(ADMIN_ID)

def is_secretario(telegram_id: int) -> bool:
    membro = buscar_membro(telegram_id)
    if not membro:
        return False
    cargo = str(membro.get("Cargo", "")).lower()
    return cargo in ["secretário", "secretario", "administrador"]

def get_nivel(telegram_id: int) -> str:
    if is_admin(telegram_id):
        return "admin"
    if is_secretario(telegram_id):
        return "secretario"
    return "membro"
