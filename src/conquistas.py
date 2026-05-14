# -*- coding: utf-8 -*-
import os
import logging
import asyncio
from datetime import datetime
from typing import Optional, Any, Dict, List

logger = logging.getLogger(__name__)

# ============================================
# CATÁLOGO DE CONQUISTAS (VITALÍCIAS)
# ============================================

CONQUISTAS_INFO = {
    "iniciado_colher": {
        "titulo": "Iniciado na Colher",
        "descricao": "Primeira confirmação de ágape realizada.",
        "emoji": "🥄",
    },
    "andarilho_marca": {
        "titulo": "Andarilho de Marca",
        "descricao": "Primeira visita a uma Loja diferente da sua cadastrada.",
        "emoji": "📍",
    },
    "sete_fronteiras": {
        "titulo": "Mestre das Sete Fronteiras",
        "descricao": "Frequência comprovada em 7 cidades ou orientes distintos.",
        "emoji": "🌍",
    },
    "noaquita_estrada": {
        "titulo": "Noaquita da Estrada",
        "descricao": "1 ano completo de caminhada e uso do sistema.",
        "emoji": "⏳",
    },
    "patriarca_sistema": {
        "titulo": "Patriarca do Sistema",
        "descricao": "2 anos ou mais de atividade ininterrupta com o bot.",
        "emoji": "📜",
    },
    "escriturario_sistema": {
        "titulo": "Escriturário do Sistema",
        "descricao": "Primeiro cadastro de sessão realizado diretamente (sem correções da IA).",
        "emoji": "✍️",
    },
    "provedor_tabernaculo": {
        "titulo": "Provedor do Tabernáculo",
        "descricao": "Primeiro cadastro de uma sessão com Ágape Gratuito.",
        "emoji": "🍷",
    },
    "guardiao_chave": {
        "titulo": "Guardião da Chave Passada",
        "descricao": "Passagem de Bastão executada, transferindo as chaves da Oficina ao sucessor.",
        "emoji": "🔑",
    },
}

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
