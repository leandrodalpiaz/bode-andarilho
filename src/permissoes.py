# src/permissoes.py
# ============================================
# BODE ANDARILHO - GERENCIAMENTO DE PERMISSÕES
# ============================================
# 
# Este módulo é responsável por determinar o nível de acesso
# de cada usuário no sistema. Os níveis são:
# 
# - "1" (comum): Pode ver eventos, confirmar presença, ver próprio perfil
# - "2" (secretário): Tudo do nível 1 + cadastrar eventos, gerenciar próprios eventos
# - "3" (admin): Tudo dos níveis 1 e 2 + promover/rebaixar, editar qualquer membro
# 
# A função get_nivel() é amplamente utilizada em todo o bot
# para controle de acesso às funcionalidades.
# 
# ============================================

from __future__ import annotations

import os
from src.sheets_supabase import buscar_membro, membro_esta_ativo


def get_nivel(user_id: int) -> str:
    """
    Retorna o nível de acesso do usuário.
    
    A função consulta a planilha para obter o nível atual do membro.
    Se o usuário não estiver cadastrado, retorna nível 1 (comum) por segurança.
    
    Args:
        user_id (int): ID do usuário no Telegram
    
    Returns:
        str: Nível de acesso:
            - "1" - comum
            - "2" - secretário
            - "3" - administrador
    """
    # Se não houver user_id, retorna nível comum
    if not user_id:
        return "1"

    # 1. Super-Admin definido por variável de ambiente tem nível 3 imediato (Recuperação de Desastre)
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id and str(user_id) == admin_id.strip():
        return "3"

    # Busca o membro na planilha
    membro = buscar_membro(user_id)
    
    # Se não encontrou, retorna nível comum
    if not membro:
        return "1"

    # Cadastro inativo/pendente não mantém permissões administrativas.
    if not membro_esta_ativo(membro):
        return "1"
    
    # Obtém o nível da planilha (padrão "1" se não existir)
    nivel = membro.get("Nivel", "1")
    
    # Garante que retorna como string limpa
    return str(nivel).strip()