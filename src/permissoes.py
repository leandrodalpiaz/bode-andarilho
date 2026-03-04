# src/permissoes.py
from __future__ import annotations

from src.sheets import buscar_membro

def get_nivel(user_id: int) -> str:
    """
    Retorna o nível de acesso do usuário:
    "1" - comum
    "2" - secretário
    "3" - administrador
    """
    if not user_id:
        return "1"
    membro = buscar_membro(user_id)
    if not membro:
        return "1"
    nivel = membro.get("Nivel", "1")
    return str(nivel).strip()