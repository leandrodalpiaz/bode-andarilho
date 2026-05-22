# src/conquistas_coletivas.py
from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, Optional

from telegram import Bot

from src.sheets_supabase import (
    checar_marco_coletivo_existente,
    listar_eventos,
    registrar_marco_coletivo,
    supabase,
    _marcar_tabela_marcos_coletivos_indisponivel,
)
from src.potencias import formatar_potencia

logger = logging.getLogger(__name__)

# Passos removidos para usar limiares globais em seu lugar
ENV_DISPAROS_COLETIVOS = "CONQUISTAS_COLETIVAS_GRUPO"


def _slugify(texto: Any) -> str:
    """Gera um slug simples, removendo acentos e caracteres especiais."""
    if not texto:
        return ""
    normalized = unicodedata.normalize("NFKD", str(texto).strip().lower())
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def _obter_grupo_central() -> Optional[int]:
    """Retorna o ID do grupo de expansão/central configurado."""
    val = os.getenv("TELEGRAM_GRUPO_EXPANSAO_ID") or os.getenv("GRUPO_PRINCIPAL_ID") or "-1003721338228"
    if not val:
        return None
    try:
        return int(float(val))
    except Exception:
        return None


def _disparos_coletivos_habilitados() -> bool:
    """Mantem os alertas coletivos pausados por padrao para evitar spam no grupo."""
    raw = (os.getenv(ENV_DISPAROS_COLETIVOS) or "").strip().lower()
    return raw in {"1", "true", "sim", "yes", "on"}


async def enviar_mensagem_coletiva(bot: Bot, texto: str):
    """Envia uma mensagem de texto formatada para o grupo central."""
    if not _disparos_coletivos_habilitados():
        logger.info(
            "Disparo coletivo suprimido: %s nao esta habilitado.",
            ENV_DISPAROS_COLETIVOS,
        )
        return
    grupo_id = _obter_grupo_central()
    if not grupo_id:
        logger.warning("Grupo central não configurado. Ignorando mensagem coletiva.")
        return
    try:
        await bot.send_message(
            chat_id=grupo_id,
            text=texto,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Erro ao enviar mensagem coletiva para o grupo %s: %s", grupo_id, e)


def obter_max_record_marco_coletivo(prefixo: str) -> int:
    """Varre os slugs cadastrados na tabela e retorna o maior valor de recorde atual."""
    try:
        from src import sheets_supabase as db

        if db._marcos_coletivos_tabela_indisponivel:
            return 0
        resp = (
            supabase.table("marcos_coletivos")
            .select("marco_slug")
            .like("marco_slug", f"{prefixo}%")
            .execute()
        )
        records = []
        for row in resp.data or []:
            slug = row.get("marco_slug", "")
            partes = slug.split("|")
            if len(partes) >= 3:
                try:
                    records.append(int(partes[-1]))
                except ValueError:
                    pass
        return max(records) if records else 0
    except Exception as e:
        if "marcos_coletivos" in str(e) and ("PGRST205" in str(e) or "schema cache" in str(e)):
            _marcar_tabela_marcos_coletivos_indisponivel(e)
            return 0
        logger.error("Erro ao obter max record para %s: %s", prefixo, e)
        return 0





def _parse_data(valor: Any) -> Optional[date]:
    """Converte valor para objeto date."""
    if not valor:
        return None
    if isinstance(valor, (datetime, date)):
        return valor if isinstance(valor, date) else valor.date()
    # Tenta usar parse_data_evento de eventos
    from src.eventos import parse_data_evento
    dt = parse_data_evento(valor)
    return dt.date() if dt else None


async def processar_conquistas_coletivas_evento(bot: Bot, evento: Dict[str, Any]) -> None:
    """
    Avalia a publicação de uma nova sessão e dispara comemorações de conquistas coletivas
    (ineditismo e novos recordes de sessões disponíveis).
    """
    try:
        if not _disparos_coletivos_habilitados():
            logger.info(
                "Conquistas coletivas pausadas: %s nao esta habilitado.",
                ENV_DISPAROS_COLETIVOS,
            )
            return

        # 1. Extração e Normalização de Campos
        loja_id = str(evento.get("loja_id") or evento.get("ID da loja") or "").strip()
        nome_loja = str(evento.get("nome_loja") or evento.get("Nome da loja") or "").strip()
        rito = str(evento.get("rito") or evento.get("Rito") or "").strip()
        grau = str(evento.get("grau") or evento.get("Grau") or "").strip()
        potencia = str(evento.get("potencia") or evento.get("Potência") or "").strip()
        potencia_comp = str(evento.get("potencia_complemento") or evento.get("Potência complemento") or "").strip()

        if not loja_id or not nome_loja:
            logger.warning("Evento sem loja_id ou nome_loja. Pulando processamento de conquistas coletivas.")
            return

        # 2. Primeira vez que a Oficina publica (Loja Pioneira)
        slug_loja = f"primeira_sessao_loja|{_slugify(loja_id)}"
        if not checar_marco_coletivo_existente(slug_loja):
            msg = (
                f"🏛️ *Nova Oficina Ativa!*\n\n"
                f"A Oficina *{nome_loja}* acaba de publicar seu primeiro convite para sessão no ecossistema Bode Andarilho!\n\n"
                f"Que a sinergia entre os Irmãos gere excelentes frutos e impulsione os trabalhos desta nova Oficina! 🤝🐐"
            )
            await enviar_mensagem_coletiva(bot, msg)
            registrar_marco_coletivo(slug_loja, "loja")

        # Obter todos os eventos ativos para cálculo de recordes de sessões simultâneas disponíveis
        eventos_ativos = listar_eventos(include_inativos=False) or []
        hoje = date.today()

        # Filtrar apenas sessões com datas futuras ou hoje (disponíveis para visita)
        sessoes_futuras = []
        for ev in eventos_ativos:
            dt_ev = _parse_data(ev.get("Data do evento") or ev.get("data_evento"))
            if dt_ev and dt_ev >= hoje:
                sessoes_futuras.append(ev)

        # 3. Rito (Ineditismo)
        if rito:
            rito_slug = _slugify(rito)
            slug_rito_primeira = f"primeira_sessao_rito|{rito_slug}"
            if not checar_marco_coletivo_existente(slug_rito_primeira):
                msg = (
                    f"📜 *Rito Pioneiro!*\n\n"
                    f"Foi publicado o primeiro convite para sessão do *{rito}* no nosso ecossistema!\n\n"
                    f"Um marco histórico para os Irmãos que trabalham sob este rito! 🏛️✨"
                )
                await enviar_mensagem_coletiva(bot, msg)
                registrar_marco_coletivo(slug_rito_primeira, "rito")

        # 4. Grau (Ineditismo)
        if grau:
            grau_slug = _slugify(grau)
            slug_grau_primeira = f"primeira_sessao_grau|{grau_slug}"
            if not checar_marco_coletivo_existente(slug_grau_primeira):
                msg = (
                    f"🌟 *Novo Grau em Loja!*\n\n"
                    f"Foi publicado o primeiro convite para sessão no grau de *{grau}* no ecossistema!\n\n"
                    f"Mais uma oportunidade de instrução e aperfeiçoamento para nossos Obreiros! 🔨"
                )
                await enviar_mensagem_coletiva(bot, msg)
                registrar_marco_coletivo(slug_grau_primeira, "grau")

        # 5. Potência (Ineditismo)
        if potencia:
            pot_nome = formatar_potencia(potencia, potencia_comp)
            pot_slug = _slugify(pot_nome)
            slug_pot_primeira = f"primeira_sessao_potencia|{pot_slug}"
            if not checar_marco_coletivo_existente(slug_pot_primeira):
                msg = (
                    f"👑 *Potência Pioneira!*\n\n"
                    f"A Potência *{pot_nome}* tem sua primeira sessão publicada no ecossistema!\n\n"
                    f"Fortalecendo a integração e o respeito mútuo em nossas estradas! 🤝"
                )
                await enviar_mensagem_coletiva(bot, msg)
                registrar_marco_coletivo(slug_pot_primeira, "potencia")

        # 6. Global Record (Sessões Ativas Disponíveis)
        total_ativas = len(sessoes_futuras)
        
        limiares_fixos = [25, 50, 100]
        def proximo_limiar(atual: int) -> int:
            if atual < 100:
                for l in limiares_fixos:
                    if l > atual:
                        return l
                return 100
            elif atual < 1000:
                return ((atual // 100) + 1) * 100
            else:
                return ((atual // 500) + 1) * 500

        max_global = obter_max_record_marco_coletivo("recorde_global_sessoes|")
        prox = proximo_limiar(max_global)
        
        if total_ativas >= prox:
            msg = (
                f"🚀 *Marco Histórico de Sessões!*\n\n"
                f"Alcançamos a marca de *{total_ativas} sessões ativas e disponíveis* "
                f"para visitação simultaneamente em nosso ecossistema!\n\n"
                f"O Bode Andarilho segue conectando Irmãos e fortalecendo nossas colunas. 🐐✨"
            )
            await enviar_mensagem_coletiva(bot, msg)
            registrar_marco_coletivo(f"recorde_global_sessoes|{total_ativas}", "global")

    except Exception as e:
        logger.error("Erro ao processar conquistas coletivas do evento: %s", e)
