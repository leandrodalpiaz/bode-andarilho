# -*- coding: utf-8 -*-
import os
import sys
import time
import traceback
from pathlib import Path

# Add root folder to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.sheets_supabase import (
    supabase,
    buscar_membro,
    cadastrar_membro,
    atualizar_membro,
    atualizar_nivel_membro,
    atualizar_status_membro,
    excluir_membro,
    listar_eventos,
    cadastrar_evento,
    atualizar_evento,
    registrar_confirmacao,
    buscar_confirmacao,
    cancelar_confirmacao,
    listar_confirmacoes_por_evento,
    cancelar_todas_confirmacoes,
)
from src.permissoes import get_nivel

# Mock test IDs
TEST_USER_1 = 999999001  # Membro Comum
TEST_USER_2 = 999999002  # Secretário
TEST_USER_3 = 999999003  # Admin
TEST_EVENT_ID = "test_event_homologacao_12345"
TEST_EVENT_ID_2 = "test_event_homologacao_67890"

# Metrics collection
metrics = {}

def measure_time(name, func, *args, **kwargs):
    start = time.perf_counter()
    res = func(*args, **kwargs)
    end = time.perf_counter()
    duration_ms = (end - start) * 1000
    metrics[name] = duration_ms
    print(f"  [METRIC] {name}: {duration_ms:.2f} ms")
    return res

def clean_up():
    print("\n--- INICIANDO LIMPEZA ---")
    try:
        # Delete confirmacoes
        supabase.table("confirmacoes").delete().in_("id_evento", [TEST_EVENT_ID, TEST_EVENT_ID_2]).execute()
        # Delete eventos
        supabase.table("eventos").delete().in_("id_evento", [TEST_EVENT_ID, TEST_EVENT_ID_2]).execute()
        # Delete membros
        for uid in [TEST_USER_1, TEST_USER_2, TEST_USER_3]:
            excluir_membro(uid)
        print("  Limpeza realizada com sucesso.")
    except Exception as e:
        print(f"  Erro na limpeza: {e}")

def run_tests():
    print("--- INICIANDO TESTES DE HOMOLOGAÇÃO ---")
    clean_up() # Clean first to avoid duplicate states
    
    success = True
    errors = []

    # ----------------------------------------------------
    # TESTE 1: Fluxo do Nível 1 - Membro Comum
    # ----------------------------------------------------
    print("\n[TESTE 1] Homologação Nível 1: Membro Comum")
    try:
        # 1.1 Cadastrar membro
        membro_data = {
            "Telegram ID": TEST_USER_1,
            "Nome": "Obreiro de Teste Comum",
            "Loja": "Loja Teste Homologacao",
            "Número da loja": "123",
            "Grau": "Aprendiz",
            "Cargo": "Membro",
            "Status": "Ativo",
            "Nivel": "1"
        }
        res = measure_time("cadastrar_membro_comum", cadastrar_membro, membro_data)
        if not res:
            raise Exception("Falha ao cadastrar membro comum")

        # 1.2 Verificar nível
        nivel = measure_time("get_nivel_membro_comum", get_nivel, TEST_USER_1)
        print(f"  Nível retornado: {nivel} (Esperado: 1)")
        if nivel != "1":
            raise Exception(f"Nível incorreto para membro comum: {nivel}")

        # 1.3 Atualizar perfil e verificar segurança de Nível
        update_data = {
            "Nome": "Obreiro de Teste Comum Alterado",
            "Nivel": "3" # Tentativa maliciosa de se promover
        }
        # Deve preservar o nível original (1)
        measure_time("atualizar_membro_comum_tentativa_promocao", atualizar_membro, TEST_USER_1, update_data, preservar_nivel=True)
        
        membro_atualizado = buscar_membro(TEST_USER_1)
        if not membro_atualizado or membro_atualizado.get("Nivel") != "1":
            raise Exception("Segurança de Nível violada! Membro conseguiu alterar o próprio nível através de atualização de perfil.")
        print("  Segurança de Nível validada: nível permaneceu '1'.")

        # 1.4 Listar eventos
        eventos = measure_time("listar_eventos_comum", listar_eventos, include_inativos=False)
        print(f"  Eventos ativos encontrados: {len(eventos)}")

        # 1.5 Confirmar presença em evento (vamos simular usando um id de evento de teste)
        # Primeiro cadastramos o evento de teste
        evento_data = {
            "ID Evento": TEST_EVENT_ID,
            "Nome da loja": "Loja Teste Homologacao",
            "Número da loja": "123",
            "Data do evento": "2026-12-25",
            "Hora": "20:00",
            "Grau": "Aprendiz",
            "Tipo de sessão": "Ordinária",
            "Ágape": "Sim",
            "Status": "Ativo"
        }
        cadastrar_evento(evento_data)

        confirmacao_data = {
            "ID Evento": TEST_EVENT_ID,
            "Telegram ID": TEST_USER_1,
            "Nome": "Obreiro de Teste Comum Alterado",
            "Grau": "Aprendiz",
            "Loja": "Loja Teste Homologacao",
            "Ágape": "Sim"
        }
        res_conf = measure_time("registrar_confirmacao_comum", registrar_confirmacao, confirmacao_data)
        if not res_conf:
            raise Exception("Falha ao registrar confirmação para membro comum")

        # 1.6 Buscar confirmação
        conf = measure_time("buscar_confirmacao_comum", buscar_confirmacao, TEST_EVENT_ID, TEST_USER_1)
        if not conf:
            raise Exception("Confirmação registrada não foi encontrada")
        print(f"  Confirmação encontrada: {conf.get('Nome')} no evento {conf.get('ID Evento')}")

        # 1.7 Cancelar confirmação
        res_canc = measure_time("cancelar_confirmacao_comum", cancelar_confirmacao, TEST_EVENT_ID, TEST_USER_1)
        if not res_canc:
            raise Exception("Falha ao cancelar confirmação")
        
        conf_pos_cancel = buscar_confirmacao(TEST_EVENT_ID, TEST_USER_1, usar_cache=False)
        if conf_pos_cancel:
            raise Exception("Confirmação ainda existe após cancelamento")
        print("  Confirmação cancelada com sucesso.")

    except Exception as e:
        success = False
        print(f"  [FALHA] Nível 1: {e}")
        errors.append(f"Nível 1: {e}\n{traceback.format_exc()}")

    # ----------------------------------------------------
    # TESTE 2: Fluxo do Nível 2 - Secretário
    # ----------------------------------------------------
    print("\n[TESTE 2] Homologação Nível 2: Secretário")
    try:
        # 2.1 Cadastrar Secretário
        sec_data = {
            "Telegram ID": TEST_USER_2,
            "Nome": "Secretário de Teste",
            "Loja": "Loja Teste Homologacao",
            "Número da loja": "123",
            "Grau": "Mestre",
            "Cargo": "Secretário",
            "Status": "Ativo",
            "Nivel": "2"
        }
        res = measure_time("cadastrar_secretario", cadastrar_membro, sec_data)
        if not res:
            raise Exception("Falha ao cadastrar secretário")
        
        # Garante o nível 2 de forma explícita
        atualizar_nivel_membro(TEST_USER_2, "2")

        # 2.2 Verificar nível
        nivel = measure_time("get_nivel_secretario", get_nivel, TEST_USER_2)
        print(f"  Nível retornado: {nivel} (Esperado: 2)")
        if nivel != "2":
            raise Exception(f"Nível incorreto para secretário: {nivel}")

        # 2.3 Cadastrar novo evento
        evento_sec_data = {
            "ID Evento": TEST_EVENT_ID_2,
            "Nome da loja": "Loja Teste Homologacao",
            "Número da loja": "123",
            "Data do evento": "2026-12-25",
            "Hora": "20:00",
            "Grau": "Companheiro",
            "Tipo de sessão": "Ordinária",
            "Ágape": "Não",
            "Status": "Ativo"
        }
        id_ev = measure_time("cadastrar_evento_secretario", cadastrar_evento, evento_sec_data)
        if not id_ev or id_ev != TEST_EVENT_ID_2:
            raise Exception("Secretário falhou ao cadastrar evento")
        print(f"  Evento cadastrado pelo secretário com ID: {id_ev}")

        # 2.4 Atualizar evento
        evento_sec_data["Hora"] = "20:30"
        res_upd = measure_time("atualizar_evento_secretario", atualizar_evento, 0, evento_sec_data)
        if not res_upd:
            raise Exception("Secretário falhou ao atualizar evento")
        print("  Evento atualizado com sucesso pelo secretário.")

    except Exception as e:
        success = False
        print(f"  [FALHA] Nível 2: {e}")
        errors.append(f"Nível 2: {e}\n{traceback.format_exc()}")

    # ----------------------------------------------------
    # TESTE 3: Fluxo do Nível 3 - Administrador
    # ----------------------------------------------------
    print("\n[TESTE 3] Homologação Nível 3: Administrador")
    try:
        # 3.1 Cadastrar Administrador
        admin_data = {
            "Telegram ID": TEST_USER_3,
            "Nome": "Administrador de Teste",
            "Loja": "Loja Teste Homologacao",
            "Número da loja": "123",
            "Grau": "Mestre",
            "Cargo": "Administrador",
            "Status": "Ativo",
            "Nivel": "3"
        }
        res = measure_time("cadastrar_admin", cadastrar_membro, admin_data)
        if not res:
            raise Exception("Falha ao cadastrar admin")
        
        # Garante o nível 3
        atualizar_nivel_membro(TEST_USER_3, "3")

        # 3.2 Verificar nível
        nivel = measure_time("get_nivel_admin", get_nivel, TEST_USER_3)
        print(f"  Nível retornado: {nivel} (Esperado: 3)")
        if nivel != "3":
            raise Exception(f"Nível incorreto para admin: {nivel}")

        # 3.3 Promover/Rebaixar outro membro (Administração de permissões)
        res_prom = measure_time("promover_membro_por_admin", atualizar_nivel_membro, TEST_USER_1, "2")
        if not res_prom:
            raise Exception("Administrador falhou ao promover membro comum a secretário")
        
        membro_promovido = buscar_membro(TEST_USER_1)
        if not membro_promovido or membro_promovido.get("Nivel") != "2":
            raise Exception("Nível do membro não foi alterado após promoção")
        print("  Membro promovido com sucesso para nível 2.")

        res_dem = measure_time("rebaixar_membro_por_admin", atualizar_nivel_membro, TEST_USER_1, "1")
        if not res_dem:
            raise Exception("Administrador falhou ao rebaixar membro")
        
        membro_rebaixado = buscar_membro(TEST_USER_1)
        if not membro_rebaixado or membro_rebaixado.get("Nivel") != "1":
            raise Exception("Nível do membro não retornou a 1 após rebaixamento")
        print("  Membro rebaixado de volta para nível 1.")

        # 3.4 Desativar/Ativar membro (Auditoria/Moderação de status)
        res_stat = measure_time("desativar_membro_por_admin", atualizar_status_membro, TEST_USER_1, "Inativo")
        if not res_stat:
            raise Exception("Administrador falhou ao alterar status de membro")
        
        membro_inativo = buscar_membro(TEST_USER_1)
        if not membro_inativo or membro_inativo.get("Status") != "Inativo":
            raise Exception("Status do membro não foi alterado para Inativo")
        print("  Membro desativado com sucesso pelo administrador.")

    except Exception as e:
        success = False
        print(f"  [FALHA] Nível 3: {e}")
        errors.append(f"Nível 3: {e}\n{traceback.format_exc()}")

    # ----------------------------------------------------
    # Finalização
    # ----------------------------------------------------
    clean_up()
    
    print("\n--- RESULTADO GERAL ---")
    if success:
        print("[SUCESSO] TODOS OS FLUXOS FORAM HOMOLOGADOS COM SUCESSO!")
    else:
        print("[ERRO] HOUVE FALHA EM UM OU MAIS FLUXOS:")
        for err in errors:
            print(f"\n{err}")

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    run_tests()
