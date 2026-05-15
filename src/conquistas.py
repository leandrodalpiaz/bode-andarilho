# -*- coding: utf-8 -*-
import os
import logging
import asyncio
import re
from datetime import datetime
from typing import Optional, Any, Dict, List

logger = logging.getLogger(__name__)

# ============================================
# CATÁLOGO DE CONQUISTAS (VITALÍCIAS)
# ============================================

CONQUISTAS_INFO = {
    "ic": {
        "titulo": "Iniciado na Colher",
        "descricao": "Primeira confirmacao de agape realizada.",
        "emoji": "🥄",
    },
    "mp": {
        "titulo": "Mestre de Marca",
        "descricao": "Visita confirmada a 5 Lojas distintas.",
        "emoji": "📍",
    },
    "e9": {
        "titulo": "Eleito dos Nove Orientes",
        "descricao": "Frequencia comprovada em 9 cidades ou orientes distintos.",
        "emoji": "🌍",
    },
    "ce": {
        "titulo": "Cavaleiro da Estrada",
        "descricao": "Visita a Lojas de 3 Estados (UF) distintos.",
        "emoji": "🛣️",
    },
    "og": {
        "titulo": "Cavaleiro do Garfo",
        "descricao": "Frequencia comprovada em 15 agapes no ecossistema.",
        "emoji": "🍷",
    },
    "pj": {
        "titulo": "Principe de Jerusalem",
        "descricao": "Presenca em Oficina com distancia superior a 200km da Loja Sede.",
        "emoji": "🏰",
    },
    "rc": {
        "titulo": "Rosa-Cruz das Visitacoes",
        "descricao": "Frequencia comprovada em Lojas de 3 ritos distintos.",
        "emoji": "🌹",
    },
    "na": {
        "titulo": "Noaquita do Asfalto",
        "descricao": "1 ano completo de registro ativo e uso do sistema.",
        "emoji": "⏳",
    },
    "rs": {
        "titulo": "Real Segredo Logistico",
        "descricao": "Presencas registradas cobrindo GOB, CMSB e COMAB.",
        "emoji": "👑",
    },
    "io": {
        "titulo": "Intendente das Oficinas",
        "descricao": "Perfil da sua Oficina 100% atualizado (GPS, CEP, Rito, Endereco).",
        "emoji": "💼",
    },
    "pm": {
        "titulo": "Mestre Passado Digital",
        "descricao": "Outorgado pela passagem bem-sucedida de Bastao ao sucessor.",
        "emoji": "🤝",
    },
}

CONQUISTAS = CONQUISTAS_INFO


# ============================================
# MOTOR DE CONCESSÃO
# ============================================

async def checar_e_conceder(user_id: int, slug: str, bot: Any) -> bool:
    """
    Verifica se o obreiro possui a conquista. Se não, concede,
    persiste no banco e envia parabéns no chat privado.
    """
    try:
        from src.sheets_supabase import listar_conquistas_obtidas, registrar_conquista
        
        slug = slug.strip().lower()
        if slug not in CONQUISTAS_INFO:
            return False
            
        conquistas = listar_conquistas_obtidas(user_id)
        if slug in conquistas:
            return False # Já possui
            
        # Grava no DB
        sucesso = registrar_conquista(user_id, slug)
        if not sucesso:
            return False
            
        # Notifica privado
        info = CONQUISTAS_INFO[slug]
        msg = (
            f"🏆 *Conquista Desbloqueada!*\n\n"
            f"Parabéns, Irmão! Você conquistou a medalha:\n"
            f"➔ *{info['emoji']} {info['titulo']}*\n\n"
            f"_{info['descricao']}_\n"
        )
        
        try:
            await bot.send_message(
                chat_id=user_id,
                text=msg,
                parse_mode="Markdown"
            )
        except Exception as ne:
            logger.warning("Conquista gravada, mas falha ao notificar user %s: %s", user_id, ne)
            
        return True
    except Exception as e:
        logger.error("Erro em checar_e_conceder para user %s, slug %s: %s", user_id, slug, e)
        return False


# ============================================
# GATILHOS DE PRESENÇA E CONFIRMAÇÃO
# ============================================

async def checar_conquistas_presenca(
    user_id: int,
    evento_dict: Dict[str, Any],
    membro_dict: Dict[str, Any],
    participacao_agape: str,
    bot: Any
) -> None:
    """
    Avalia as conquistas atreladas ao ato de confirmar presença.
    Executado de forma segura e assíncrona.
    """
    try:
        # 1. Iniciado na Colher (Primeiro Ágape)
        if participacao_agape and "sim" in str(participacao_agape).lower():
            await checar_e_conceder(user_id, "iniciado_colher", bot)
            
        # 2. Andarilho de Marca (Visita a loja diferente)
        m_loja = str(membro_dict.get("Loja", membro_dict.get("loja", ""))).strip().lower()
        m_num = str(membro_dict.get("Número da loja", membro_dict.get("numero_loja", ""))).strip()
        
        e_loja = str(evento_dict.get("Nome da loja", evento_dict.get("nome_loja", ""))).strip().lower()
        e_num = str(evento_dict.get("Número da loja", evento_dict.get("numero_loja", ""))).strip()
        
        eh_visita = False
        if m_loja and e_loja:
            if m_loja != e_loja:
                eh_visita = True
            elif m_num and e_num and m_num != e_num and m_num != "0":
                eh_visita = True
                
        if eh_visita:
            await checar_e_conceder(user_id, "andarilho_marca", bot)
            
        # 3. Mestre das Sete Fronteiras (7 cidades visitadas)
        from src.sheets_supabase import buscar_confirmacoes_membro, listar_eventos
        
        confirmacoes = await buscar_confirmacoes_membro(user_id)
        if not confirmacoes:
            return
            
        ids_eventos_visitados = {str(c.get("ID Evento") or c.get("id_evento")) for c in confirmacoes}
        
        # Adiciona o evento atual caso ainda não esteja retornado pelo DB
        id_ev_atual = str(evento_dict.get("ID Evento") or evento_dict.get("id_evento") or evento_dict.get("id", ""))
        if id_ev_atual:
            ids_eventos_visitados.add(id_ev_atual)
            
        # Pull all events to map cities
        def _fetch_ev():
            return listar_eventos(include_passados=True)
        all_events = await asyncio.to_thread(_fetch_ev)
        
        cidades_visitadas = set()
        for ev in all_events:
            ev_id = str(ev.get("ID Evento") or ev.get("id_evento") or ev.get("id", ""))
            if ev_id in ids_eventos_visitados:
                oriente = str(ev.get("Oriente", "")).strip().split("/")[0].title()
                if oriente and oriente not in ("Não Informado", ""):
                    cidades_visitadas.add(oriente)
                    
        if len(cidades_visitadas) >= 7:
            await checar_e_conceder(user_id, "sete_fronteiras", bot)
            
    except Exception as e:
        logger.error("Erro em checar_conquistas_presenca para user %s: %s", user_id, e)


# ============================================
# GATILHOS COLETIVOS (EXPANSÃO)
# ============================================

async def checar_e_disparar_marco_coletivo(bot: Any, dados_loja: Dict[str, Any]) -> None:
    """
    Avalia se o cadastro de uma Loja dispara marcos de expansão coletiva no Grupo Principal.
    """
    try:
        from src.sheets_supabase import checar_marco_coletivo_existente, registrar_marco_coletivo
        
        grupo_id_str = os.getenv("GRUPO_PRINCIPAL_ID", "")
        if not grupo_id_str:
            return
            
        try:
            grupo_id = int(grupo_id_str)
        except Exception:
            return
            
        potencia = str(dados_loja.get("potencia", dados_loja.get("Potência", ""))).strip().upper()
        comp = str(dados_loja.get("potencia_complemento", dados_loja.get("Potência complemento", ""))).strip().upper()
        uf = str(dados_loja.get("estado_uf", dados_loja.get("Oriente", "").split("/")[-1])).strip().upper()
        nome_loja = dados_loja.get("nome", dados_loja.get("Nome", ""))
        num_loja = dados_loja.get("numero", dados_loja.get("Número da loja", ""))
        
        if "/" in uf:
            uf = uf.split("/")[-1].strip()
            
        # 1. Arco da Integração
        if potencia:
            chave_pot = f"{potencia} - {comp}" if comp else potencia
            slug_arco = f"arco_integracao|{chave_pot.lower().replace(' ', '_')}"
            
            if not checar_marco_coletivo_existente(slug_arco):
                msg = (
                    f"🏛️ *O Arco da Integração*\n\n"
                    f"Primeira Loja da Potência *{chave_pot}* registrada no sistema!\n"
                    f"Seja bem-vinda **{nome_loja}, nº {num_loja}**.\n\n"
                    f"A integração nacional avança! 📐🚀"
                )
                try:
                    await bot.send_message(chat_id=grupo_id, text=msg, parse_mode="Markdown")
                    registrar_marco_coletivo(slug_arco, "arco_integracao")
                except Exception as ge:
                    logger.error("Erro ao enviar Arco da Integração para grupo: %s", ge)

        # 2. Expansão Geográfica
        if uf and len(uf) == 2:
            slug_geo = f"expansao_geo|{uf.lower()}"
            if not checar_marco_coletivo_existente(slug_geo):
                msg = (
                    f"🚩 *Expansão Geográfica*\n\n"
                    f"O sistema chegou ao Estado de **{uf}**!\n"
                    f"Primeira Loja cadastrada na região: **{nome_loja}, nº {num_loja}**.\n\n"
                    f"Nossas colunas se expandem! 🌍"
                )
                try:
                    await bot.send_message(chat_id=grupo_id, text=msg, parse_mode="Markdown")
                    registrar_marco_coletivo(slug_geo, "expansao_geografica")
                except Exception as ge:
                    logger.error("Erro ao enviar Expansão Geo para grupo: %s", ge)
                    
    except Exception as e:
        logger.error("Erro geral em checar_e_disparar_marco_coletivo: %s", e)


# ============================================
# JOB CRON ANUAL (ANIVERSÁRIO DE CADASTRO)
# ============================================

async def checar_aniversarios_cadastro(bot: Any) -> None:
    """
    Job de cron semanal que varre os membros ativos verificando anos de casa.
    """
    try:
        from src.sheets_supabase import listar_membros_ativos
        membros = listar_membros_ativos()
        
        agora = datetime.now()
        for m in membros:
            user_id_str = m.get("Telegram ID") or m.get("telegram_id")
            if not user_id_str:
                continue
            try:
                user_id = int(float(user_id_str))
            except Exception:
                continue
                
            data_cad_str = m.get("Data de cadastro") or m.get("data_cadastro")
            if not data_cad_str:
                continue
                
            dt_cad = None
            for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt_cad = datetime.strptime(str(data_cad_str)[:19].strip(), fmt)
                    break
                except Exception:
                    continue
                    
            if not dt_cad:
                continue
                
            diferenca = agora - dt_cad
            anos = diferenca.days // 365
            
            if anos >= 2:
                await checar_e_conceder(user_id, "patriarca_sistema", bot)
            elif anos >= 1:
                await checar_e_conceder(user_id, "noaquita_estrada", bot)
                
    except Exception as e:
        logger.error("Erro em job checar_aniversarios_cadastro: %s", e)




# ============================================
# APURAÇÃO MASSIVA DE MERITOS (DIPLOMA ENGINE)
# ============================================

async def verificar_novas_conquistas(user_id: int, bot: Any) -> None:
    """
    Executa a varredura agregada de estatisticas de presencas,
    cidades, UFs e prazos para outorgar automaticamente novas medalhas.
    Invocado transparente e assincronamente antes da abertura de Perfil.
    """
    try:
        from src.sheets_supabase import (
            buscar_membro,
            buscar_confirmacoes_membro,
            supabase,
            _row_to_sheets
        )
        
        uid = int(float(user_id))
        membro = buscar_membro(uid)
        if not membro:
            return
            
        # 1. Buscar Historico de Confirmacoes
        confirmacoes = await buscar_confirmacoes_membro(uid)
        if not confirmacoes:
            confirmacoes = []
            
        # 2. Buscar Metadados dos Eventos confirmados
        eventos = []
        ids_eventos = list({c.get("ID Evento") or c.get("id_evento") for c in confirmacoes if c.get("ID Evento") or c.get("id_evento")})
        if ids_eventos:
            def _fetch_evs():
                resp = supabase.table("eventos").select("*").in_("id_evento", ids_eventos).execute()
                return [_row_to_sheets("eventos", r) for r in (resp.data or [])]
            eventos = await asyncio.to_thread(_fetch_evs)
            
        # 3. Buscar Lojas vinculadas a esses eventos
        lojas_visitadas_db = []
        ids_lojas = list({str(ev.get("ID da loja") or ev.get("loja_id")) for ev in eventos if ev.get("ID da loja") or ev.get("loja_id")})
        if ids_lojas:
            def _fetch_lojas():
                resp = supabase.table("lojas").select("*").in_("id", ids_lojas).execute()
                return [_row_to_sheets("lojas", r) for r in (resp.data or [])]
            lojas_visitadas_db = await asyncio.to_thread(_fetch_lojas)
            
        # 4. Buscar Loja Sede do membro
        loja_sede = None
        loja_sede_id = membro.get("loja_id") or membro.get("ID da loja")
        if loja_sede_id:
            def _fetch_sede():
                resp = supabase.table("lojas").select("*").eq("id", loja_sede_id).execute()
                if resp.data:
                    return _row_to_sheets("lojas", resp.data[0])
                return None
            loja_sede = await asyncio.to_thread(_fetch_sede)
            
        # ==========================================
        # APURAÇÃO E AGREGAÇÃO DE CONJUNTOS
        # ==========================================
        
        # AGAPES
        contagem_agape = sum(1 for c in confirmacoes if "sim" in str(c.get("Ágape") or c.get("agape") or "").lower())
        
        # LOJAS
        lojas_visitadas_set = set()
        for ev in eventos:
            lid = str(ev.get("ID da loja") or ev.get("loja_id") or "").strip()
            if lid:
                lojas_visitadas_set.add(lid)
            else:
                nome_l = str(ev.get("Nome da loja") or ev.get("nome_loja") or "").strip().lower()
                if nome_l:
                    lojas_visitadas_set.add(nome_l)
                    
        # CIDADES (ORIENTES)
        cidades_visitadas = set()
        for ev in eventos:
            ori = str(ev.get("Oriente") or ev.get("oriente") or "").strip()
            # Limpa e extrai a cidade
            cid = ori.split("-")[0].split("/")[0].strip().title()
            if cid and cid not in ("Nao Informado", "Não Informado", ""):
                cidades_visitadas.add(cid)
                
        # UFS, RITOS E POTÊNCIAS
        ufs_visitados = set()
        ritos_visitados = set()
        potencias_visitadas = set()
        
        for lj in lojas_visitadas_db:
            uf = str(lj.get("Estado UF") or lj.get("estado_uf") or "").strip().upper()
            if uf: ufs_visitados.add(uf)
            rit = str(lj.get("Rito") or lj.get("rito") or "").strip().upper()
            if rit: ritos_visitados.add(rit)
            pot = str(lj.get("Potência") or lj.get("potencia") or "").strip().upper()
            if pot: potencias_visitadas.add(pot)
            
        # Fallbacks via parsing de strings para resiliencia legada
        for ev in eventos:
            ori = str(ev.get("Oriente") or ev.get("oriente") or "").strip().upper()
            m_uf = re.search(r"[-\/]\s*([A-Z]{2})$", ori)
            if m_uf:
                ufs_visitados.add(m_uf.group(1))
                
            rit = str(ev.get("Rito") or ev.get("rito") or "").strip().upper()
            if rit: ritos_visitados.add(rit)
            
            pot = str(ev.get("Potência") or ev.get("potencia") or "").strip().upper()
            if pot: potencias_visitadas.add(pot)
            
        # ==========================================
        # VERIFICAÇÃO INDIVIDUAL DE REGRAS
        # ==========================================
        
        # 🥄 IC: Iniciado na Colher (Count Agape >= 1)
        if contagem_agape >= 1:
            await checar_e_conceder(uid, "ic", bot)
            
        # 🍷 OG: Cavaleiro do Garfo (Count Agape >= 15)
        if contagem_agape >= 15:
            await checar_e_conceder(uid, "og", bot)
            
        # 📍 MP: Mestre de Marca (Lojas distintas >= 5)
        if len(lojas_visitadas_set) >= 5:
            await checar_e_conceder(uid, "mp", bot)
            
        # 🌍 E9: Eleito dos Nove Orientes (Cidades >= 9)
        if len(cidades_visitadas) >= 9:
            await checar_e_conceder(uid, "e9", bot)
            
        # 🛣️ CE: Cavaleiro da Estrada (UFs distintas >= 3)
        if len(ufs_visitados) >= 3:
            await checar_e_conceder(uid, "ce", bot)
            
        # 🌹 RC: Rosa-Cruz das Visitações (Ritos distintos >= 3)
        if len(ritos_visitados) >= 3:
            await checar_e_conceder(uid, "rc", bot)
            
        # 👑 RS: Principe do Real Segredo (GOB, CMSB e COMAB)
        tem_gob = any("GOB" in p for p in potencias_visitadas)
        tem_cmsb = any("CMSB" in p or "GL" in p for p in potencias_visitadas) # CMSB costuma ter GL (Grandes Lojas)
        tem_comab = any("COMAB" in p or "GOP" in p for p in potencias_visitadas) # COMAB/GOP
        if tem_gob and tem_cmsb and tem_comab:
            await checar_e_conceder(uid, "rs", bot)
            
        # 🏰 PJ: Principe de Jerusalem (Distancia > 200km - Heuristica UF diferente)
        if loja_sede:
            sede_uf = str(loja_sede.get("Estado UF") or loja_sede.get("estado_uf") or "").strip().upper()
            if sede_uf:
                for lj in lojas_visitadas_db:
                    v_uf = str(lj.get("Estado UF") or lj.get("estado_uf") or "").strip().upper()
                    if v_uf and v_uf != sede_uf:
                        await checar_e_conceder(uid, "pj", bot)
                        break
                        
        # ⏳ NA: Noaquita do Asfalto (Data Cadastro >= 365 dias)
        data_cad_str = membro.get("Data de cadastro") or membro.get("data_cadastro")
        if data_cad_str:
            dt_cad = None
            for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt_cad = datetime.strptime(str(data_cad_str)[:19].strip(), fmt)
                    break
                except:
                    pass
            if dt_cad:
                if (datetime.now() - dt_cad).days >= 365:
                    await checar_e_conceder(uid, "na", bot)
                    
        # 💼 IO: Intendente das Oficinas (Secretario com perfil 100% preenchido)
        nivel = str(membro.get("Nivel") or membro.get("nivel") or "1").strip()
        if nivel in ("2", "2.5", "3") and loja_sede:
            end = str(loja_sede.get("Endereço") or loja_sede.get("endereco") or "").strip()
            cep = str(loja_sede.get("CEP") or loja_sede.get("cep") or "").strip()
            cid = str(loja_sede.get("Cidade") or loja_sede.get("cidade") or "").strip()
            uf = str(loja_sede.get("Estado UF") or loja_sede.get("estado_uf") or "").strip()
            rit = str(loja_sede.get("Rito") or loja_sede.get("rito") or "").strip()
            pot = str(loja_sede.get("Potência") or loja_sede.get("potencia") or "").strip()
            if all([end, cep, cid, uf, rit, pot]):
                await checar_e_conceder(uid, "io", bot)
                
    except Exception as e:
        logger.error("Erro em verificar_novas_conquistas para %s: %s", user_id, e)


# ============================================
# INTERFACE DE COMANDOS DO BOT
# ============================================

async def cmd_conquistas(update: Any, context: Any) -> None:
    """
    Handler do comando /conquistas e callback 'abrir_galeria'.
    Exibe o menu principal da Sala de Trofeus.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from src.bot import navegar_para
    from src.sheets_supabase import buscar_membro
    
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
            
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    
    if not membro:
        msg = "Irmao, para abrir sua Galeria de Conquistas, voce precisa concluir seu registro primeiro. Use /start."
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
        
    texto = (
        "🏆 *Sala de Troféus e Conquistas*\n\n"
        "Seja bem-vindo, Ir.·.!\n"
        "Aqui voce pode acompanhar a sua jornada de gamificacao no ecossistema. "
        "Consulte suas medalhas de andarilho, o vigor historico da sua Oficina ou gere um Quadro de Honra em alta resolucao.\n\n"
        "Escolha sua inspecao heraldica:"
    )
    
    from src.miniapp import _webapp_base_url
    btn_app = []
    base_url = _webapp_base_url()
    if base_url:
        # Inclui o deep-linking startapp=galeria
        url_galeria = f"{base_url}/webapp/galeria?startapp=galeria"
        from telegram import WebAppInfo
        btn_app = [InlineKeyboardButton("📱 Abrir Sala no Mini App", web_app=WebAppInfo(url=url_galeria))]

    teclado_lista = [
        [InlineKeyboardButton("🎖️ Minhas Medalhas", callback_data="galeria_medalhas")],
        [InlineKeyboardButton("🏆 Conquistas da Oficina", callback_data="galeria_oficina")],
        [InlineKeyboardButton("🖼️ Gerar Quadro de Honra", callback_data="galeria_gerar_quadro")]
    ]
    if btn_app:
        teclado_lista.insert(0, btn_app)
        
    teclado_lista.append([InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_principal")])
    teclado = InlineKeyboardMarkup(teclado_lista)
    
    await navegar_para(update, context, "Galeria", texto, teclado)


async def menu_galeria_medalhas(update: Any, context: Any) -> None:
    """
    Lista em formato textual estendido as 11 medalhas e o status de desbloqueio.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from src.bot import navegar_para
    from src.sheets_supabase import buscar_membro, get_galeria_completa
    
    query = update.callback_query
    if query:
        await query.answer()
        
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    loja_id = membro.get("loja_id") or membro.get("ID da loja")
    
    galeria = get_galeria_completa(user_id, loja_id)
    individuais = galeria.get("conquistas_individuais", [])
    
    texto = "🎖️ *Minhas Medalhas Individuais*\n\n"
    
    linhas = []
    for b in individuais:
        status = "🟢 Conquistada" if b.get("desbloqueada") else "🔴 Bloqueada"
        info_local = CONQUISTAS_INFO.get(b["slug"], {})
        emoji = info_local.get("emoji", "🏅")
        linhas.append(f"{emoji} *{b['titulo']}* — {status}\n_{b['descricao']}_\n")
        
    texto += "\n".join(linhas)
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Gerar Quadro de Honra", callback_data="galeria_gerar_quadro")],
        [InlineKeyboardButton("🔙 Voltar à Galeria", callback_data="abrir_galeria")]
    ])
    
    await navegar_para(update, context, "Minhas Medalhas", texto, teclado)


async def menu_galeria_oficina(update: Any, context: Any) -> None:
    """
    Lista os selos de vigor obtidos pela oficina nos ultimos 6 meses e marcos globais.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from src.bot import navegar_para
    from src.sheets_supabase import buscar_membro, get_galeria_completa
    
    query = update.callback_query
    if query:
        await query.answer()
        
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    loja_id = membro.get("loja_id") or membro.get("ID da loja")
    
    galeria = get_galeria_completa(user_id, loja_id)
    marcos_of = galeria.get("marcos_oficina", [])
    marcos_exp = galeria.get("marcos_expansao", [])
    
    texto = "🏆 *Conquistas da Oficina & Expansão*\n\n"
    texto += "🏛️ *Vigor Administrativo (Últimos 6 meses):*\n"
    
    if not marcos_of:
        texto += "_Nenhum selo de vigor ou excelencia registrado recentemente._\n\n"
    else:
        for m in marcos_of:
            selos = []
            if m.get("excelencia"): selos.append("Oficina de Excelencia 🎗️")
            if m.get("farol"): selos.append("Farol da Regiao 🎗️")
            texto += f"• *{m['mes_formatado']}*: {', '.join(selos)}\n"
        texto += "\n"
        
    texto += "🌍 *Marcos Globais e Coletivos:*\n"
    if not marcos_exp:
        texto += "_A expansao heraldica global segue em andamento._\n"
    else:
        for e in marcos_exp:
            texto += f"• 🚩 *{e['titulo']}*\n"
            
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Gerar Quadro de Honra", callback_data="galeria_gerar_quadro")],
        [InlineKeyboardButton("🔙 Voltar à Galeria", callback_data="abrir_galeria")]
    ])
    
    await navegar_para(update, context, "Conquistas Oficina", texto, teclado)


async def menu_gerar_quadro(update: Any, context: Any) -> None:
    """
    Dispara a engine Pillow, apaga o menu texto e posta o card comemorativo 1200x675.
    """
    query = update.callback_query
    if query:
        try:
            await query.answer("Forjando seu Quadro de Honra... 🔨🔥", show_alert=False)
            await query.message.delete()
        except:
            pass
            
    user_id = update.effective_user.id
    from src.sheets_supabase import buscar_membro, get_galeria_completa
    
    membro = buscar_membro(user_id)
    nome_membro = membro.get("Nome") or membro.get("nome") or "Obreiro"
    loja_id = membro.get("loja_id") or membro.get("ID da loja")
    
    dados = get_galeria_completa(user_id, loja_id)
    nome_loja = dados.get("nome_loja", "Oficina")
    
    from src.render_marcos import renderizar_badge_wall
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    try:
        caminho_png = renderizar_badge_wall(dados, nome_membro, nome_loja)
        
        if caminho_png and os.path.exists(caminho_png):
            teclado = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Voltar à Galeria", callback_data="abrir_galeria")]
            ])
            
            with open(caminho_png, "rb") as photo:
                msg_enviada = await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption="📜 *Quadro de Honra e Sala de Troféus*\n\n"
                            "Obreiro autenticado e lacrado com o selo de autenticidade digital.",
                    parse_mode="Markdown",
                    reply_markup=teclado
                )
                
            # Regista no rastreador para navegacao limpa
            from src.bot import estado_mensagens, TIPO_RESULTADO
            if user_id not in estado_mensagens:
                estado_mensagens[user_id] = {}
            estado_mensagens[user_id][TIPO_RESULTADO] = {
                "message_id": msg_enviada.message_id,
                "content_hash": None
            }
            
            # Clean-up local seguro
            try:
                os.remove(caminho_png)
            except:
                pass
        else:
            raise FileNotFoundError("Imagem nao gerada.")
            
    except Exception as e:
        logger.error("Erro ao renderizar e despachar quadro de honra: %s", e)
        from src.bot import _enviar_ou_editar_mensagem, TIPO_RESULTADO
        teclado_err = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar à Galeria", callback_data="abrir_galeria")]])
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO, 
            "⚠️ *Erro de Fundição heráldica!*\nNão conseguimos compor seu Quadro de Honra gráfico agora. Consulte as telas de texto temporariamente.",
            teclado_err
        )
