# -*- coding: utf-8 -*-
import os
import logging
import asyncio
from typing import Any, Dict, List, Optional
from telegram import Bot, InputMediaPhoto
from src.sheets_supabase import (
    supabase,
    _row_to_sheets,
    registrar_marco_coletivo,
    checar_marco_coletivo_existente,
    get_total_confirmacoes,
    is_first_of_potencia,
    listar_lojas
)
from src.render_marcos import renderizar_card_celebracao

logger = logging.getLogger(__name__)

def _obter_grupo_central() -> Optional[int]:
    """Busca o ID do grupo principal nas variáveis de ambiente."""
    id_str = os.getenv("GRUPO_PRINCIPAL_ID") or os.getenv("CENTRAL_GROUP_ID")
    if not id_str:
        return None
    try:
        return int(float(str(id_str).strip()))
    except Exception:
        return None

async def _enviar_card_telegram(bot: Bot, file_path: str, caption: str):
    """Envia a imagem com legenda para o grupo central de forma segura."""
    chat_id = _obter_grupo_central()
    if not chat_id:
        logger.warning("Nenhum GRUPO_PRINCIPAL_ID configurado. O Card nao pode ser enviado.")
        return
        
    try:
        with open(file_path, "rb") as photo:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode="Markdown"
            )
        logger.info("Alerta coletivo enviado para o grupo %s com sucesso.", chat_id)
    except Exception as e:
        logger.error("Erro ao enviar card para Telegram no chat %s: %s", chat_id, e)
    finally:
        # Limpeza física temporária
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass


async def processar_alerta_fundacao(dados_loja: Dict[str, Any], bot: Any) -> None:
    """
    Avalia metadados da loja recem aprovada e escolhe o maior nivel
    de alerta coletivo para disparo no grupo de expansao.
    """
    try:
        # Padroniza chaves (pode vir de INSERT Supabase com chaves minúsculas)
        nome = str(dados_loja.get("nome") or dados_loja.get("Nome da Loja") or "").strip()
        num = str(dados_loja.get("numero") or dados_loja.get("Número da loja") or "").strip()
        uf = str(dados_loja.get("estado_uf") or dados_loja.get("Estado UF") or "").strip().upper()
        pot = str(dados_loja.get("potencia") or dados_loja.get("Potência") or "").strip().upper()
        comp = str(dados_loja.get("potencia_complemento") or dados_loja.get("Potência complemento") or "").strip().upper()
        
        if not nome: return
        
        cidade = str(dados_loja.get("cidade") or dados_loja.get("Cidade") or "").strip().title()
        sigla_pot = pot
        if comp:
            sigla_pot = f"{pot} - {comp}"
            
        # 1. CHECAR CRUZ VERMELHA TERRITORIAL (INEDITISMO UF)
        if uf and len(uf) == 2:
            slug_uf = f"expansao_geo|{uf.lower()}"
            if not checar_marco_coletivo_existente(slug_uf):
                # Marco territorial inédito!
                registrar_marco_coletivo(slug_uf, "expansao_territorial")
                
                card_path = renderizar_card_celebracao(
                    tipo_marco="Cruz Vermelha Territorial",
                    titulo=f"Expansão em {uf}",
                    subtitulo=f"A malha de visitação chega ao Estado de {uf}!",
                    detalhes=f"Loja Pioneira: {nome} nº {num}\\n{cidade} / {uf}",
                    potencia=pot.lower(),
                    monograma_selo="EX"
                )
                
                msg = (
                    f"🚩 *Fronteiras Expandidas!*\n\n"
                    f"O Bode Andarilho orgulhosamente finca sua coluna no Estado de **{uf}**!\n\n"
                    f"Seja muito bem-vinda **{nome} nº {num}**, a nossa primeira Oficina Oficial em terras do oriente de **{cidade}/{uf}**. A malha de visitação avança! 🌍📐🚩"
                )
                await _enviar_card_telegram(bot, card_path, msg)
                return # Previne disparo duplo
                
        # 2. CHECAR ARCO DA INTEGRAÇÃO (PRIMEIRA LOJA DESTA POTÊNCIA COMPLETA)
        if pot:
            chave_pot = f"{pot}_{comp}".lower().replace(" ", "_").strip("_")
            slug_pot = f"arco_integracao|{chave_pot}"
            
            # Verifica se a contagem no banco de dados valida o ineditismo real
            if is_first_of_potencia(pot, comp) and not checar_marco_coletivo_existente(slug_pot):
                registrar_marco_coletivo(slug_pot, "arco_integracao")
                
                card_path = renderizar_card_celebracao(
                    tipo_marco="Arco da Integração",
                    titulo=f"Pioneira {pot}",
                    subtitulo=f"Primeira Loja da Potência {sigla_pot} erguida!",
                    detalhes=f"Oficina: {nome} nº {num}\\n{cidade} / {uf}",
                    potencia=pot.lower(),
                    monograma_selo="AI"
                )
                
                msg = (
                    f"🏛️ *Nova Coluna Erguida!*\n\n"
                    f"Registramos a primeira Oficina vinculada à Potência **{sigla_pot}**!\n\n"
                    f"Nossas colunas recebem a **{nome} nº {num}** ({cidade}/{uf}). Parabéns aos Irmãos pela integração federativa! 📐🚀"
                )
                await _enviar_card_telegram(bot, card_path, msg)
                return
                
        # 3. ALERTA PADRÃO: FUNDAÇÃO DE OFICINA
        card_path = renderizar_card_celebracao(
            tipo_marco="Fundação de Oficina",
            titulo=f"{nome} nº {num}",
            subtitulo=f"Oficina Oficial instalada e chancelada no ecossistema!",
            detalhes=f"Potência: {sigla_pot}\\n{cidade} / {uf}",
            potencia=pot.lower(),
            monograma_selo="FO"
        )
        
        msg = (
            f"🏛️ *Sessão de Instalação Concluída!*\n\n"
            f"A Loja **{nome} nº {num}** ({sigla_pot}) de **{cidade}/{uf}** agora é uma Oficina Oficial em nosso sistema!\n\n"
            f"O Malhete da Administração foi chancelado e as portas estão abertas para a malha de visitação digital! 📜🤝🐐"
        )
        await _enviar_card_telegram(bot, card_path, msg)
        
    except Exception as e:
        logger.error("Erro no Heraldo ao processar alerta de fundacao: %s", e)


async def checar_marcos_mobilizacao(bot: Any) -> None:
    """
    Varredura horária de contagem agregada de confirmacoes
    para bater metas globais e disparar a comemoracao de mobilizacao.
    """
    try:
        total = get_total_confirmacoes()
        if not total or total <= 0:
            return
            
        milestones = [100, 500, 1000, 2500, 5000, 10000, 25000]
        
        for meta in milestones:
            if total >= meta:
                slug = f"mobilizacao|{meta}"
                if not checar_marco_coletivo_existente(slug):
                    # Bateu a meta e não foi anunciado
                    registrar_marco_coletivo(slug, "conselho_mobilizacao")
                    
                    card_path = renderizar_card_celebracao(
                        tipo_marco="Conselho de Mobilização",
                        titulo=f"{meta:,} Presenças",
                        subtitulo=f"Vigor em movimento! Meta histórica superada!",
                        detalhes=f"Total Acumulado: {total:,} Confirmações\\nObrigado, Obreiros!",
                        potencia="gob", # Default watermark
                        monograma_selo="MO"
                    )
                    
                    msg = (
                        f"🔥 *Vigor em Movimento!*\n\n"
                        f"Alcançamos o marco épico de **{meta:,} presenças confirmadas** no ecossistema Bode Andarilho!\n\n"
                        f"Atualmente somamos **{total:,} confirmações** ativas. A egrégora agradece o empenho de cada Irmão que fortalece nossas colunas na estrada! 🤝🐐🚜🔥"
                    )
                    await _enviar_card_telegram(bot, card_path, msg)
                    break # Apenas um marco por rodada
                    
    except Exception as e:
        logger.error("Erro em checar_marcos_mobilizacao: %s", e)


async def realizar_abertura_historica(bot: Any) -> None:
    """
    Executa o Rito de Abertura Historica.
    Consolida silenciosamente marcos passados e envia UMA mensagem
    institucional inaugural e o card de mobilizacao consolidada.
    """
    try:
        slug_abertura = "abertura_historica_realizada"
        if checar_marco_coletivo_existente(slug_abertura):
            return # Ja rodou anteriormente
            
        logger.info("--- INICIANDO RITO DE ABERTURA HISTÓRICA DA CHANCELARIA ---")
        
        # 1. Puxar todas as Lojas existentes
        lojas = listar_lojas()
        
        ufs_encontradas = set()
        potencias_encontradas = set()
        
        for l in lojas:
            # Registro silencioso de UFs
            uf = str(l.get("Estado UF") or l.get("estado_uf") or "").strip().upper()
            if uf and len(uf) == 2:
                slug_uf = f"expansao_geo|{uf.lower()}"
                registrar_marco_coletivo(slug_uf, "expansao_territorial")
                ufs_encontradas.add(uf)
                
            # Registro silencioso de Potências
            pot = str(l.get("Potência") or l.get("potencia") or "").strip().upper()
            comp = str(l.get("Potência complemento") or l.get("potencia_complemento") or "").strip().upper()
            if pot:
                chave_pot = f"{pot}_{comp}".lower().replace(" ", "_").strip("_")
                slug_pot = f"arco_integracao|{chave_pot}"
                registrar_marco_coletivo(slug_pot, "arco_integracao")
                
                nome_p = f"{pot} - {comp}" if comp else pot
                potencias_encontradas.add(nome_p)
                
        # 2. Registrar marcos de mobilizacao retroativos
        total = get_total_confirmacoes()
        milestones = [100, 500, 1000, 2500, 5000, 10000, 25000]
        maior_meta = 0
        
        for m in milestones:
            if total >= m:
                slug_mob = f"mobilizacao|{m}"
                registrar_marco_coletivo(slug_mob, "conselho_mobilizacao")
                maior_meta = m
                
        # 3. Disparar Mensagem de Texto Inaugural
        lista_ufs = ", ".join(sorted(list(ufs_encontradas))) or "Nenhuma ainda"
        lista_pots = "\\n- ".join(sorted(list(potencias_encontradas))) or "Nenhuma"
        
        msg_inaugural = (
            f"🏛️ *RITO DE INSTALAÇÃO DA CHANCELARIA DE EXPANSÃO*\n\n"
            f"Saudações, Respeitáveis Obreiros e Secretários!\n\n"
            f"Oficializamos neste ato a abertura da Coluna de Comunicação e Expansão Institucional do ecossistema Bode Andarilho. 📢✨\n\n"
            f"Realizamos a varredura e chancela dos registros passados:\n"
            f"🌍 *Estados Conquistados:* {lista_ufs}\n"
            f"🏛️ *Potências Federativas na Rede:*\n- {lista_pots}\n\n"
            f"Consolidados históricos devidamente lacrados e integrados. A malha oficializa hoje o primeiro grande marco de mobilização global obtido até este momento:"
        )
        
        # Pega o chat ID central
        chat_id = _obter_grupo_central()
        if chat_id:
            # Envia a mensagem textual primeiro
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=msg_inaugural,
                    parse_mode="Markdown"
                )
            except Exception as e_msg:
                logger.warning("Falha ao enviar texto inaugural: %s", e_msg)
                
            # 4. Gera e envia o card consolidado de mobilizacao
            card_path = renderizar_card_celebracao(
                tipo_marco="Abertura de Chancelaria",
                titulo=f"{total:,} Presenças",
                subtitulo="Vigor Histórico Consolidado!",
                detalhes=f"Malha ativa inaugurada em produção!\\nA egrégora em movimento.",
                potencia="gob",
                monograma_selo="MO"
            )
            
            caption = f"📜 *Primeiro Selo Histórico Fundido!*\n\nO ecossistema inicia suas comunicações já ostentando a marca cumulada de **{total:,} presenças confirmadas**. Nossos sinceros agradecimentos a todos os Irmãos!"
            await _enviar_card_telegram(bot, card_path, caption)
            
        # Grava que a abertura ocorreu para nunca repetir
        registrar_marco_coletivo(slug_abertura, "sistemico")
        logger.info("[OK] Rito de Abertura Historica concluido com sucesso!")
        
    except Exception as e:
        logger.error("Erro critico no Rito de Abertura Historica: %s", e)
