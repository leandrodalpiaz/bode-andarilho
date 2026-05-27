# -*- coding: utf-8 -*-
"""
Bode Andarilho - Script de Simulação de Cenários 🐐
Este script simula detalhadamente as seguintes operações:
1. Cadastramento de uma Loja com sucesso.
2. Publicação de sessões pelo Secretário com 3 modos visuais:
   - template_padrao (Arte sugerida pelo sistema)
   - card_especial (Arte própria da sessão)
   - template_loja (Arte em branco da loja com injeção de textos)
3. Cadastramento de novo usuário e ativação.
4. Confirmação de presença de nível 1 por botão no grupo e por botão no privado.
5. Cancelamento de presença e consumo dos dados pelo Secretário e pelo Usuário.
"""

import sys
import json
from datetime import datetime

# Cores para formatação de console
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def print_section(title):
    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}{CYAN}🐐 {title.upper()}{RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")

def print_step(step, desc):
    print(f"{BOLD}{BLUE}[PASSO {step}] {desc}{RESET}")

def print_data(label, data):
    print(f"{YELLOW}{label}:{RESET}")
    print(json.dumps(data, indent=2, ensure_ascii=False))

# --- BANCO DE DADOS EM MEMÓRIA ---
db = {
    "lojas": [],
    "eventos": [],
    "membros": [],
    "confirmacoes": [],
    "notificacoes_secretario_pendentes": []
}

# --- TEMPLATES DE MENSAGENS (MOCKADO DE src/messages.py) ---
CONFIRMACAO_SECRETARIO_TMPL = (
    "✅ *Presença confirmada, irmão {nome}!*\n\n"
    "Resumo:\n"
    "📅 {data} — {loja} nº {numero}\n"
    "🕕 Horário: {horario}\n"
    "🍽 {participacao}\n\n"
    "📢 *Nova confirmação registrada*"
)

CONFIRMACAO_COM_AGAPE_TMPL = (
    "Ir.·., agradecemos sua visita! Presença CONFIRMADA (Com Ágape) para a sessão: \"{pauta}\" na Loja {loja} nº {numero}.\n\n"
    "📅 {data} às {horario}\n\n"
    "⚠️ Pedimos que cancelamentos sejam feitos com 24h de antecedência para nossa melhor organização.\n\n"
    "⚠️ A confirmação via bot não garante o ingresso no templo, permanecendo necessárias as verificações habituais. 🐐"
)

CONFIRMACAO_SEM_AGAPE_TMPL = (
    "Ir.·., agradecemos sua visita! Presença CONFIRMADA (Sem Ágape) para a sessão: \"{pauta}\" na Loja {loja} nº {numero}.\n\n"
    "📅 {data} às {horario}\n\n"
    "⚠️ A confirmação via bot não garante o ingresso no templo, permanecendo necessárias as verificações habituais. 🐐"
)

NOTIFICACAO_NOVA_CONFIRMACAO = (
    "📢 *A COLUNA AUMENTA*\n\n"
    "👤 *Irmão:* {nome}\n"
    "📅 *Sessão:* {data} - {loja}\n"
    "🍽 *Participação no Ágape:* {agape}\n"
)

PRESENCA_CANCELADA = (
    "❌ A sua presença foi removida da lista.\n\n"
    "Caso os seus planos mudem e possa estar conosco, a sua confirmação será bem-vinda."
)

# --- SIMULAÇÃO DE CENÁRIOS ---

def rodar_simulacao():
    sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

    # ==================================================================
    # CENÁRIO 1: Cadastramento de Loja
    # ==================================================================
    print_section("Cenário 1: Cadastramento de uma Loja com Sucesso")
    print_step(1.1, "Secretário inicia o cadastramento de sua Loja.")
    
    sec_id = 999999002  # Telegram ID do Secretário
    sec_nome = "Irmão Marcos Silva"

    dados_loja = {
        "nome": "Fraternidade e Progresso",
        "numero": "456",
        "oriente": "São Paulo - SP",
        "rito": "REAA",
        "potencia": "GOSP",
        "potencia_complemento": "GOB",
        "endereco": "Rua das Acácias, 123, Centro, São Paulo - SP",
        "secretario_responsavel_id": str(sec_id),
        "secretario_responsavel_nome": sec_nome,
        "template_sessao_url": "https://supabase.co/storage/v1/object/public/templates/loja_456_blank.png"
    }
    
    print_data("Dados enviados pelo Secretário no formulário/bot", dados_loja)

    print_step(1.2, "Processando a inserção no Supabase (função `cadastrar_loja`)")
    
    row_loja = {
        "id": "1", # ID gerado automaticamente
        "telegram_id": str(sec_id),
        "secretario_responsavel_id": str(sec_id),
        "secretario_responsavel_nome": sec_nome,
        "vinculo_atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "vinculo_atualizado_por_id": str(sec_id),
        "nome_loja": dados_loja["nome"],
        "numero": dados_loja["numero"],
        "oriente_loja": dados_loja["oriente"],
        "rito": dados_loja["rito"],
        "potencia": dados_loja["potencia"],
        "potencia_complemento": dados_loja["potencia_complemento"],
        "endereco": dados_loja["endereco"],
        "data_cadastro": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "template_sessao_url": dados_loja["template_sessao_url"]
    }
    
    db["lojas"].append(row_loja)
    print(f"{GREEN}✔ Registro inserido com sucesso na tabela 'lojas'!{RESET}")
    print_data("Registro salvo na tabela 'lojas'", row_loja)

    # ==================================================================
    # CENÁRIO 2: Publicação de Sessões (Três Tipos de Card)
    # ==================================================================
    print_section("Cenário 2: Publicação de Eventos/Sessões (3 Modos Visuais)")
    print("O Secretário 'Marcos Silva' irá criar três sessões diferentes:")
    
    # Evento A: template_padrao
    print_step(2.1, "Sessão A: Usando o Card Padrão do Sistema (template_padrao)")
    evento_a = {
        "id_evento": "EVT_PADRAO_001",
        "loja_id": "1",
        "nome_loja": "Fraternidade e Progresso",
        "numero_loja": "456",
        "data_evento": "10/06/2026",
        "hora": "20:00",
        "grau": "Aprendiz",
        "tipo_sessao": "Ordinária",
        "rito": "REAA",
        "potencia": "GOSP",
        "potencia_complemento": "GOB",
        "pauta": "Instrução do Primeiro Grau",
        "agape": "Sim",
        "endereco": "Rua das Acácias, 123",
        "secretario_telegram_id": str(sec_id),
        "modo_visual": "template_padrao",
        "status": "Ativo"
    }
    db["eventos"].append(evento_a)
    print(f"{GREEN}✔ Evento A cadastrado no banco com modo_visual='template_padrao'{RESET}")
    
    print_data("Dados do Evento A no banco", evento_a)
    print(f"{BOLD}Simulação de Publicação Visual (preparar_midia_evento):{RESET}")
    print("  -> Modo visual detectado: 'template_padrao'")
    print("  -> Renderizador utiliza o template padrão em: assets/templates/default_event_card.png")
    print("  -> Texto injetado por cima: 'Loja Fraternidade e Progresso nº 456 | REAA - GOSP'")
    print("  -> Salva renderização no storage bucket e obtém URL pública.")
    print("  -> Telegram envia FOTO com botões de confirmação:")
    print(f"     [Card Renderizado Padrão (FOTO)]")
    print(f"     Legenda: \"Confirme sua presença pelos botões abaixo.\"")
    print(f"     Botões: [ 🍽 Presença + Ágape ]  [ 🏛 Presença Apenas ]")

    # Evento B: card_especial
    print_step(2.2, "Sessão B: Usando Arte Própria / Card Especial (card_especial)")
    evento_b = {
        "id_evento": "EVT_ESPECIAL_002",
        "loja_id": "1",
        "nome_loja": "Fraternidade e Progresso",
        "numero_loja": "456",
        "data_evento": "17/06/2026",
        "hora": "20:00",
        "grau": "Companheiro",
        "tipo_sessao": "Ordinária",
        "rito": "REAA",
        "potencia": "GOSP",
        "pauta": "Palestra Magna - Arte e Filosofia",
        "agape": "Sim",
        "endereco": "Rua das Acácias, 123",
        "secretario_telegram_id": str(sec_id),
        "modo_visual": "card_especial",
        "card_especial_url": "https://supabase.co/storage/v1/object/public/event-specials/palestra_comp_flyer.png",
        "status": "Ativo"
    }
    db["eventos"].append(evento_b)
    print(f"{GREEN}✔ Evento B cadastrado no banco com modo_visual='card_especial'{RESET}")
    
    print_data("Dados do Evento B no banco", evento_b)
    print(f"{BOLD}Simulação de Publicação Visual (preparar_midia_evento):{RESET}")
    print("  -> Modo visual detectado: 'card_especial'")
    print("  -> Baixa a imagem diretamente de: card_especial_url")
    print("  -> Nenhuma injeção de textos é feita. O card especial pronto é usado diretamente.")
    print("  -> Telegram envia FOTO no grupo com botões de confirmação:")
    print(f"     [Flyer de Divulgação da Loja (FOTO)]")
    print(f"     Legenda: \"Confirme sua presença pelos botões abaixo.\"")
    print(f"     Botões: [ 🍽 Presença + Ágape ]  [ 🏛 Presença Apenas ]")

    # Evento C: template_loja
    print_step(2.3, "Sessão C: Usando Arte em Branco da Loja para Injeção (template_loja)")
    evento_c = {
        "id_evento": "EVT_LOJA_003",
        "loja_id": "1",
        "nome_loja": "Fraternidade e Progresso",
        "numero_loja": "456",
        "data_evento": "24/06/2026",
        "hora": "20:00",
        "grau": "Mestre",
        "tipo_sessao": "Ordinária",
        "rito": "REAA",
        "potencia": "GOSP",
        "pauta": "Regularização de Templo",
        "agape": "Sim",
        "endereco": "Rua das Acácias, 123",
        "secretario_telegram_id": str(sec_id),
        "modo_visual": "template_loja",
        "status": "Ativo"
    }
    db["eventos"].append(evento_c)
    print(f"{GREEN}✔ Evento C cadastrado no banco com modo_visual='template_loja'{RESET}")
    
    print_data("Dados do Evento C no banco", evento_c)
    print(f"{BOLD}Simulação de Publicação Visual (preparar_midia_evento):{RESET}")
    print("  -> Modo visual detectado: 'template_loja'")
    print("  -> Recupera a loja vinculada (ID 1).")
    print("  -> Obtém o template da loja em: template_sessao_url (https://supabase.co/storage/v1/object/public/templates/loja_456_blank.png)")
    print("  -> O sistema desenha os textos dinâmicos por cima desse template personalizado:")
    print("     * Pauta: 'Regularização de Templo'")
    print("     * Data: '24/06/2026 às 20:00'")
    print("     * Grau: 'Mestre'")
    print("  -> Salva a foto renderizada e envia no grupo:")
    print(f"     [Template da Loja + Textos Injetados (FOTO)]")
    print(f"     Legenda: \"Confirme sua presença pelos botões abaixo.\"")
    print(f"     Botões: [ 🍽 Presença + Ágape ]  [ 🏛 Presença Apenas ]")

    # ==================================================================
    # CENÁRIO 3: Cadastramento de Novo Usuário (Obreiro)
    # ==================================================================
    print_section("Cenário 3: Cadastramento e Ativação de um Novo Usuário")
    print_step(3.1, "Novo obreiro inicia o cadastro no privado.")
    
    user_id = 999999001
    user_nome = "Gabriel Souza"
    
    membro_dados = {
        "telegram_id": str(user_id),
        "nome": user_nome,
        "loja": "Cavaleiros da Luz",
        "numero_loja": "789",
        "oriente": "Campinas - SP",
        "grau": "Aprendiz",
        "cargo": "Membro",
        "potencia": "GLESP",
        "status": "Pendente",  # Começa pendente
        "nivel": "1"
    }
    
    db["membros"].append(membro_dados)
    print(f"{GREEN}✔ Registro do novo usuário salvo como 'Pendente'!{RESET}")
    print_data("Registro salvo na tabela 'membros'", membro_dados)

    print_step(3.2, "Secretário aprova o cadastro do membro através de um botão.")
    
    # Simula a atualização do status para Ativo
    for m in db["membros"]:
        if m["telegram_id"] == str(user_id):
            m["status"] = "Ativo"
            m["status_auditoria"] = "Aprovado"
    
    print(f"{GREEN}✔ Status do membro atualizado para 'Ativo' no banco de dados!{RESET}")
    print_data("Registro atualizado na tabela 'membros'", db["membros"][-1])

    # ==================================================================
    # CENÁRIO 4: Confirmações de Presença (Grupo e Privado)
    # ==================================================================
    print_section("Cenário 4: Confirmações de Presença (Nível 1)")
    
    # 4.1 Confirmação no Grupo (Evento A - Grau Aprendiz - Gabriel Souza)
    print_step(4.1, "Gabriel Souza (Aprendiz) clica no botão 'Presença + Ágape' no Grupo da Oficina.")
    print("  -> Callback recebido pelo Bot: 'confirmar|EVT_PADRAO_001|gratuito'")
    
    # Validações internas do bot:
    # 1. Busca membro no banco:
    membro = next((m for m in db["membros"] if m["telegram_id"] == str(user_id)), None)
    print(f"  -> Membro localizado: {membro['nome']} | Status: {membro['status']}")
    # 2. Confere se está ativo:
    print(f"  -> Membro está ativo? {membro['status'] == 'Ativo'}")
    # 3. Confere o Grau (Membro Aprendiz vs Evento Aprendiz):
    print(f"  -> Grau do membro ({membro['grau']}) é compatível com o do evento ({evento_a['grau']})? Sim.")
    
    # Registra a confirmação
    conf_a = {
        "id_evento": "EVT_PADRAO_001",
        "telegram_id": str(user_id),
        "nome": membro["nome"],
        "grau": membro["grau"],
        "cargo": membro["cargo"],
        "loja": membro["loja"],
        "numero_loja": membro["numero_loja"],
        "oriente": membro["oriente"],
        "potencia": membro["potencia"],
        "agape": "Confirmada (Gratuito)",
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }
    db["confirmacoes"].append(conf_a)
    print(f"{GREEN}✔ Confirmação registrada com sucesso na tabela 'confirmacoes'!{RESET}")
    print_data("Dados da confirmação no banco", conf_a)

    # Telegram Updates:
    # A) Bot edita a lista de confirmados no grupo (se for o tipo lista) ou envia o feedback.
    # B) Bot envia mensagem privada para o usuário Gabriel confirmando:
    msg_gabriel = CONFIRMACOES_DB_TO_SHEETS = CONFIRMACAO_COM_AGAPE_TMPL.format(
        pauta=evento_a["pauta"],
        loja=evento_a["nome_loja"],
        numero=evento_a["numero_loja"],
        data=evento_a["data_evento"],
        horario=evento_a["hora"]
    )
    print(f"\n{BOLD}[CHAT PRIVADO - GABRIEL SOUZA]{RESET}")
    print(msg_gabriel)

    # C) Bot envia mensagem privada para o Secretário Marcos notificando a nova presença:
    msg_notif_sec = NOTIFICACAO_NOVA_CONFIRMACAO.format(
        nome=membro["nome"],
        data=evento_a["data_evento"],
        loja=f"{evento_a['nome_loja']} nº {evento_a['numero_loja']}",
        agape="Confirmada (Gratuito)"
    )
    print(f"\n{BOLD}[CHAT PRIVADO - SECRETÁRIO MARCOS SILVA (Notificação)]{RESET}")
    print(msg_notif_sec)

    # 4.2 Confirmação no Privado (Evento A - Secretário Marcos se auto-confirma)
    print_step(4.2, "O Secretário Marcos Silva confirma presença para si mesmo no Privado do Bot.")
    print("  -> Marcos navega até 'Sessões Disponíveis' -> 'EVT_PADRAO_001'")
    print("  -> Clica em 'Confirmar Presença (Sem Ágape)'")
    
    # Registra no banco
    conf_sec = {
        "id_evento": "EVT_PADRAO_001",
        "telegram_id": str(sec_id),
        "nome": sec_nome,
        "grau": "Mestre",
        "cargo": "Secretário",
        "loja": "Fraternidade e Progresso",
        "numero_loja": "456",
        "oriente": "São Paulo - SP",
        "potencia": "GOSP",
        "agape": "Não",
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }
    db["confirmacoes"].append(conf_sec)
    print(f"{GREEN}✔ Confirmação do Secretário registrada!{RESET}")
    print_data("Dados da confirmação do Secretário no banco", conf_sec)

    # Mensagem enviada para Marcos (tom diferenciado CONFIRMACAO_SECRETARIO_TMPL)
    msg_marcos = CONFIRMACAO_SECRETARIO_TMPL.format(
        nome=sec_nome,
        data=evento_a["data_evento"],
        loja=evento_a["nome_loja"],
        numero=evento_a["numero_loja"],
        horario=evento_a["hora"],
        participacao="Não participará do ágape",
        bloco_importancia=""
    )
    print(f"\n{BOLD}[CHAT PRIVADO - SECRETÁRIO MARCOS SILVA]{RESET}")
    print(msg_marcos)

    # ==================================================================
    # CENÁRIO 5: Cancelamento de Presença e Consumo dos Dados
    # ==================================================================
    print_section("Cenário 5: Cancelamento de Presença e Consumo de Dados")
    print_step(5.1, "Gabriel Souza decide cancelar sua presença na sessão EVT_PADRAO_001.")
    print("  -> Gabriel entra no bot, vai em 'Minhas Presenças' -> Seleciona a sessão A.")
    print("  -> Clica em '❌ Cancelar presença'.")
    
    # Remove do banco de dados (cancelar_confirmacao)
    db["confirmacoes"] = [c for c in db["confirmacoes"] if not (c["id_evento"] == "EVT_PADRAO_001" and c["telegram_id"] == str(user_id))]
    print(f"{GREEN}✔ Registro de confirmação excluído com sucesso da tabela 'confirmacoes'!{RESET}")
    
    # Resposta para o usuário no privado:
    print(f"\n{BOLD}[CHAT PRIVADO - GABRIEL SOUZA]{RESET}")
    print(PRESENCA_CANCELADA)

    # 5.2 Como os dados são consumidos pelo Secretário
    print_step(5.2, "O Secretário Marcos Silva consulta o status de confirmados do evento.")
    print("  -> Marcos entra no painel, clica em 'Ver Resumo' ou '📋 Copiar lista de confirmados'")
    
    # Simula a geração do resumo para o Secretário (resumo_confirmados)
    confirmados_evento = [c for c in db["confirmacoes"] if c["id_evento"] == "EVT_PADRAO_001"]
    total = len(confirmados_evento)
    com_agape = sum(1 for c in confirmados_evento if "confirmada" in c["agape"].lower())
    sem_agape = sum(1 for c in confirmados_evento if c["agape"].lower() == "não")
    
    resumo_sec = (
        f"📊 *RESUMO DA SESSÃO*\n\n"
        f"🏛 {evento_a['nome_loja']} nº {evento_a['numero_loja']}\n"
        f"📅 {evento_a['data_evento']} - {evento_a['hora']}\n\n"
        f"✅ *Total de confirmados:* {total}\n"
        f"🍽 *Com ágape:* {com_agape}\n"
        f"🚫 *Sem ágape:* {sem_agape}\n\n"
        f"*Lista resumida:*\n"
    )
    for c in confirmados_evento:
        prefixo = "VM " if "instalado" in c["grau"].lower() or c["cargo"].lower() == "venerável mestre" else ""
        resumo_sec += f"• {prefixo}{c['nome']} - {c['grau']} ({'Com ágape' if 'confirmada' in c['agape'].lower() else 'Sem ágape'})\n"
        
    print(f"\n{BOLD}[TELA DO BOT - VISÃO DO SECRETÁRIO (Resumo de Confirmados)]{RESET}")
    print(resumo_sec)

    # 5.3 Como os dados são consumidos pelo próprio Usuário (Gabriel Souza)
    print_step(5.3, "O usuário Gabriel Souza consulta suas próprias confirmações (minhas_confirmacoes_futuro).")
    
    minhas_conf = [c for c in db["confirmacoes"] if c["telegram_id"] == str(user_id)]
    
    print(f"\n{BOLD}[TELA DO BOT - VISÃO DO OBREIRO GABRIEL SOUZA (Próximas Sessões)]{RESET}")
    if not minhas_conf:
        print("📅 *Próximas sessões*\n\nVocê não possui confirmações para as próximas sessões.")
    else:
        for mc in minhas_conf:
            print(f"• {mc['id_evento']} - {mc['loja']} (Confirmado)")

if __name__ == "__main__":
    rodar_simulacao()
