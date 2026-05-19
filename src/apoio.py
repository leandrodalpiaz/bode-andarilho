# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from src.bot import navegar_para
from src.permissoes import get_nivel
from src.sheets_supabase import supabase

logger = logging.getLogger(__name__)
BRANDING_DIR = Path(__file__).resolve().parent.parent / "assets" / "branding"
PIX_CHAVE_PADRAO = os.getenv("APOIO_PIX_CHAVE", "bodeandarilho@gmail.com")
PIX_TIPO_PADRAO = os.getenv("APOIO_PIX_TIPO", "Chave PIX")
PIX_BANCO_PADRAO = os.getenv("APOIO_PIX_BANCO", "").strip()

TIPO_CARD = "card_logo"
TIPO_CONF = "confirmados_premium_texto"
TIPO_IA = "ia_resposta_texto"
TIPO_TELA = "tela_apoiadores"

_FREQ_IA_MOD = 3


def doacoes_ativas() -> bool:
    return os.getenv("APOIO_DOACOES_ATIVAS", "false").strip().lower() in {"1", "true", "sim", "yes", "on"}


@dataclass
class ApoiadorElegivel:
    apoiador_id: str
    contrato_id: str
    nome: str
    categoria: str
    texto_curto: str
    link_publico: str
    peso: int
    limites: Dict[str, int]


def _today_iso() -> str:
    return date.today().isoformat()


def _safe_table(name: str):
    if not supabase:
        return None
    return supabase.table(name)


def _fetch_rows(table: str, filters: Optional[List[Tuple[str, str, object]]] = None) -> List[Dict]:
    t = _safe_table(table)
    if t is None:
        return []
    try:
        q = t.select("*")
        for op, key, val in filters or []:
            if op == "eq":
                q = q.eq(key, val)
            elif op == "lte":
                q = q.lte(key, val)
            elif op == "gte":
                q = q.gte(key, val)
        res = q.execute()
        return list((res.data or []))
    except Exception as exc:
        logger.warning("Falha ao consultar %s: %s", table, exc)
        return []


def buscar_apoiadores_ativos() -> List[Dict]:
    return _fetch_rows("apoiadores", [("eq", "status", "ativo")])


def buscar_contratos_vigentes() -> List[Dict]:
    today = _today_iso()
    return _fetch_rows(
        "apoios_contratos",
        [("eq", "status", "ativo"), ("lte", "data_inicio", today), ("gte", "data_fim", today)],
    )


def _contar_exibicoes_mes(apoiador_id: str, tipo_exibicao: str) -> int:
    t = _safe_table("apoios_exibicoes")
    if t is None:
        return 0
    try:
        ini_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        res = (
            t.select("id", count="exact")
            .eq("apoiador_id", apoiador_id)
            .eq("tipo_exibicao", tipo_exibicao)
            .gte("created_at", ini_mes)
            .execute()
        )
        return int(res.count or 0)
    except Exception as exc:
        logger.warning("Falha ao contar exibicoes (%s/%s): %s", apoiador_id, tipo_exibicao, exc)
        return 0


def _limite_key(tipo_exibicao: str) -> str:
    return {
        TIPO_CARD: "limite_card_mes",
        TIPO_CONF: "limite_confirmados_mes",
        TIPO_IA: "limite_ia_mes",
    }.get(tipo_exibicao, "")


def _categoria_peso(cat: str) -> int:
    return {"master": 10, "destaque": 6, "institucional": 3, "amigo_projeto": 1}.get((cat or "").lower(), 1)


def _listar_elegiveis(tipo_exibicao: str) -> List[ApoiadorElegivel]:
    apoiadores = {a.get("id"): a for a in buscar_apoiadores_ativos() if a.get("id")}
    contratos = buscar_contratos_vigentes()
    configs = {c.get("apoiador_id"): c for c in _fetch_rows("apoios_config") if c.get("apoiador_id")}

    elegiveis: List[ApoiadorElegivel] = []
    for c in contratos:
        aid = c.get("apoiador_id")
        if not aid or aid not in apoiadores:
            continue

        cfg = configs.get(aid, {})
        if tipo_exibicao == TIPO_CARD and not bool(cfg.get("permite_logo_card")):
            continue
        if tipo_exibicao == TIPO_CONF and not bool(cfg.get("permite_confirmados")):
            continue
        if tipo_exibicao == TIPO_IA and not bool(cfg.get("permite_ia")):
            continue

        limite_col = _limite_key(tipo_exibicao)
        limite = int(cfg.get(limite_col) or 0)
        if limite > 0 and _contar_exibicoes_mes(aid, tipo_exibicao) >= limite:
            continue

        ap = apoiadores[aid]
        texto = str(ap.get("texto_curto") or "").strip()
        if tipo_exibicao in (TIPO_CONF, TIPO_IA) and not texto:
            continue

        peso = int(cfg.get("peso_prioridade") or 1) + _categoria_peso(str(c.get("categoria") or ""))
        elegiveis.append(
            ApoiadorElegivel(
                apoiador_id=str(aid),
                contrato_id=str(c.get("id") or ""),
                nome=str(ap.get("nome") or "Apoiador"),
                categoria=str(c.get("categoria") or "institucional"),
                texto_curto=texto,
                link_publico=str(ap.get("link_publico") or "").strip(),
                peso=max(1, peso),
                limites={"mes": limite},
            )
        )
    return elegiveis


def _weighted_pick(elegiveis: List[ApoiadorElegivel], limite: int) -> List[ApoiadorElegivel]:
    pool = list(elegiveis)
    picks: List[ApoiadorElegivel] = []
    while pool and len(picks) < limite:
        chosen = random.choices(pool, weights=[x.peso for x in pool], k=1)[0]
        picks.append(chosen)
        pool = [p for p in pool if p.apoiador_id != chosen.apoiador_id]
    return picks


def selecionar_apoiador_para_card() -> Optional[Dict]:
    elegiveis = _listar_elegiveis(TIPO_CARD)
    if not elegiveis:
        placeholders = [
            BRANDING_DIR / "sponsor_placeholder_1.png",
            BRANDING_DIR / "sponsor_placeholder_2.png",
            BRANDING_DIR / "sponsor_placeholder_3.png",
        ]
        existentes = [p for p in placeholders if p.exists()]
        if not existentes:
            return None
        pick = random.choice(existentes)
        return {
            "apoiador_id": "placeholder",
            "contrato_id": "",
            "nome": "Espaço de apoio disponível",
            "logo_path": str(pick),
        }
    escolhido = _weighted_pick(elegiveis, 1)[0]
    return {"apoiador_id": escolhido.apoiador_id, "contrato_id": escolhido.contrato_id, "nome": escolhido.nome}


def selecionar_apoiadores_para_confirmados(limite: int = 2) -> List[Dict]:
    elegiveis = _listar_elegiveis(TIPO_CONF)
    picks = [x.__dict__ for x in _weighted_pick(elegiveis, limite)]
    if picks:
        return picks
    return [
        {
            "apoiador_id": "placeholder",
            "contrato_id": "",
            "nome": "Divulgue sua marca ou projeto",
            "texto_curto": "Exiba seu Instagram, link ou contato neste espaço. Uma presença sutil e amigável para toda a nossa comunidade.",
        },
        {
            "apoiador_id": "placeholder2",
            "contrato_id": "",
            "nome": "Apoie a manutenção do Bode Andarilho",
            "texto_curto": "Colabore com a hospedagem, suporte técnico e melhorias do aplicativo por meio de uma inserção discreta.",
        },
    ][:limite]


def selecionar_apoiadores_para_ia(limite: int = 2) -> List[Dict]:
    elegiveis = _listar_elegiveis(TIPO_IA)
    picks = [x.__dict__ for x in _weighted_pick(elegiveis, limite)]
    if picks:
        return picks
    return [
        {
            "apoiador_id": "placeholder",
            "contrato_id": "",
            "nome": "Divulgue sua marca aqui",
            "texto_curto": "exiba seu Instagram, site ou contato por meio de uma inserção institucional discreta.",
        }
    ][:limite]


def montar_botao_apoiadores() -> List[List[InlineKeyboardButton]]:
    return [[InlineKeyboardButton("🤝 Ver apoiadores", callback_data="apoio_ver_apoiadores")]]


def montar_rodape_confirmados() -> Tuple[str, Optional[InlineKeyboardMarkup], List[Dict]]:
    picks = selecionar_apoiadores_para_confirmados(2)
    if not picks:
        return "", None, []
    linhas = ["", "—", "🤝 Apoio à manutenção do Bode Andarilho", ""]
    for p in picks:
        linhas.append(f"📌 {p['nome']}")
        linhas.append(str(p.get("texto_curto") or "Apoio institucional à manutenção do projeto."))
        linhas.append("")
    return "\n".join(linhas).rstrip(), InlineKeyboardMarkup(montar_botao_apoiadores()), picks


def resposta_ia_elegivel_para_apoio(resposta: str) -> bool:
    t = (resposta or "").strip().lower()
    if len(t) < 120:
        return False
    bloqueios = ["erro", "não sei", "nao sei", "permiss", "negad"]
    return not any(b in t for b in bloqueios)


def montar_rodape_ia(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[str, Optional[InlineKeyboardMarkup], List[Dict]]:
    if not context.user_data:
        return "", None, []
    seq = int(context.user_data.get("apoio_ia_seq") or 0) + 1
    context.user_data["apoio_ia_seq"] = seq
    if seq % _FREQ_IA_MOD != 0:
        return "", None, []

    picks = selecionar_apoiadores_para_ia(2)
    if not picks:
        return "", None, []

    if len(picks) == 1:
        texto = (
            "\n\n—\n"
            "🤝 Apoio à manutenção e melhorias do Bode Andarilho:\n"
            f"{picks[0]['nome']} — {picks[0].get('texto_curto') or 'Apoio institucional ao projeto.'}"
        )
    else:
        texto = (
            "\n\n—\n"
            "🤝 Apoiam a manutenção do Bode Andarilho:\n"
            f"• {picks[0]['nome']} — {picks[0].get('texto_curto') or 'Apoio institucional.'}\n"
            f"• {picks[1]['nome']} — {picks[1].get('texto_curto') or 'Apoio institucional.'}"
        )
    return texto, InlineKeyboardMarkup(montar_botao_apoiadores()), picks


def registrar_exibicao_apoio(apoiador_id: str, contrato_id: str, tipo_exibicao: str, contexto: str = "", evento_id: str = "", usuario_id: Optional[int] = None) -> None:
    if str(apoiador_id).startswith("placeholder"):
        return
    t = _safe_table("apoios_exibicoes")
    if t is None:
        return
    try:
        t.insert(
            {
                "apoiador_id": apoiador_id,
                "contrato_id": contrato_id or None,
                "tipo_exibicao": tipo_exibicao,
                "contexto": contexto or None,
                "evento_id": evento_id or None,
                "usuario_id": usuario_id,
            }
        ).execute()
    except Exception as exc:
        logger.warning("Falha ao registrar exibicao de apoio: %s", exc)


async def mostrar_apoiadores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass

    vigentes = {c.get("apoiador_id") for c in buscar_contratos_vigentes() if c.get("apoiador_id")}
    ativos = [a for a in buscar_apoiadores_ativos() if a.get("id") in vigentes]
    ativos = ativos[:10]

    if not ativos:
        texto = (
            "🤝 *Apoiadores do Bode Andarilho*\n\n"
            "Este espaço está aberto a marcas e profissionais que queiram apoiar a continuidade do projeto.\n\n"
            "📌 *Espaço de apoio disponível*\n"
            "Exiba seu Instagram, site ou contato. Uma presença discreta e elegante em telas de grande visualização, como listas de confirmados, cards de eventos e respostas da inteligência artificial.\n\n"
            "📌 *Apoie o Bode Andarilho*\n"
            "Sua contribuição ajuda a cobrir custos de hospedagem, manutenção técnica e melhorias para a nossa comunidade.\n\n"
            "Deseja apoiar este projeto? Toque em *Falar com admin* e a administração receberá seu interesse."
        )
    else:
        texto = (
            "🤝 *Apoiadores do Bode Andarilho*\n\n"
            "O Bode Andarilho é mantido com apoio destinado à hospedagem, manutenção técnica e melhorias contínuas.\n\n"
        )
        for a in ativos:
            texto += f"• *{a.get('nome','Apoiador')}*"
            tc = str(a.get("texto_curto") or "").strip()
            if tc:
                texto += f" — {tc}"
            texto += "\n"

    botoes = []
    for a in ativos:
        link = str(a.get("link_publico") or "").strip()
        if link:
            botoes.append([InlineKeyboardButton(f"🌐 {a.get('nome','Apoiador')}", url=link)])
    botoes.append([InlineKeyboardButton("💬 Falar com admin", callback_data="apoio_contato_admin")])
    if doacoes_ativas():
        botoes.append([InlineKeyboardButton("💝 Doar ao projeto", callback_data="apoio_doar")])
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")])

    await navegar_para(update, context, "Apoiadores", texto, InlineKeyboardMarkup(botoes))
    for a in ativos:
        registrar_exibicao_apoio(str(a.get("id")), "", TIPO_TELA, contexto="tela_apoiadores")


async def cmd_apoiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass
    texto = (
        "🤝 *Apoio Institucional*\n\n"
        "O Bode Andarilho oferece espaços de apoio para marcas e profissionais que desejam colaborar com a comunidade de forma sutil.\n\n"
        "Apoiar o projeto ajuda a manter custos de hospedagem, manutenção técnica e melhorias contínuas, com divulgação discreta em pontos estratégicos do aplicativo.\n\n"
        "Exemplos de inserção: seu Instagram, site ou contato. O objetivo é integrar parceiros à comunidade sem comprometer a experiência de uso.\n\n"
        "Faixas sugeridas: Amigo, Institucional, Destaque e Master."
    )
    await navegar_para(
        update,
        context,
        "Apoio Institucional",
        texto,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 Apoiadores", callback_data="apoio_ver_apoiadores")],
            [InlineKeyboardButton("💬 Falar com admin", callback_data="apoio_contato_admin")],
            *([[InlineKeyboardButton("💝 Doar ao projeto", callback_data="apoio_doar")]] if doacoes_ativas() else []),
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")],
        ]),
    )


async def falar_com_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        try:
            await q.answer("A administração será notificada sobre o seu interesse.", show_alert=False)
        except Exception:
            pass

    user = update.effective_user
    admin_id = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
    nome = "Interessado"
    if user:
        nome = " ".join([p for p in [user.first_name, user.last_name] if p]) or user.username or str(user.id)

    texto_usuario = (
        "💬 *Interesse registrado!*\n\n"
        "A administração do projeto foi notificada e entrará em contato em breve.\n\n"
        "Para agilizar o processo, você pode preparar:\n"
        "• O nome da sua marca, empresa ou projeto;\n"
        "• Seu link de preferência (Instagram, site ou outro contato);\n"
        "• Uma frase curta de apresentação (amigável e discreta);\n"
        "• A faixa de apoio de seu interesse."
    )
    await navegar_para(
        update,
        context,
        "Apoio Institucional > Contato",
        texto_usuario,
        InlineKeyboardMarkup([
            *([[InlineKeyboardButton("💝 Doar ao projeto", callback_data="apoio_doar")]] if doacoes_ativas() else []),
            [InlineKeyboardButton("🔙 Voltar", callback_data="apoiar_menu")],
        ]),
    )

    if admin_id.isdigit() and user:
        try:
            username = f"@{user.username}" if user.username else "sem username público"
            await context.bot.send_message(
                chat_id=int(admin_id),
                text=(
                    "Novo interessado em apoio institucional:\n\n"
                    f"Nome: {nome}\n"
                    f"Telegram ID: {user.id}\n"
                    f"Username: {username}\n\n"
                    "Sugestão: responder no privado para solicitar a marca, link, contato e faixa de apoio desejada."
                ),
            )
        except Exception as exc:
            logger.warning("Falha ao notificar admin sobre interesse em apoio: %s", exc)


async def mostrar_doacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass

    if not doacoes_ativas():
        await navegar_para(
            update,
            context,
            "Apoio Institucional > Doação",
            "💝 *Doação ao projeto*\n\nEsta opção ainda não está ativa nesta fase.\n\nSe você deseja apoiar o projeto como parceiro institucional, toque em *Falar com admin*.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Falar com admin", callback_data="apoio_contato_admin")],
                [InlineKeyboardButton("🔙 Voltar", callback_data="apoiar_menu")],
            ]),
        )
        return

    qr_path = BRANDING_DIR / "pix_doacao_bode_andarilho.png"
    texto = (
        "💝 *Doação ao projeto*\n\n"
        "Qualquer valor contribui diretamente para a manutenção do Bode Andarilho: custos de hospedagem, banco de dados, suporte técnico e melhorias contínuas.\n\n"
        f"*{PIX_TIPO_PADRAO}:* `{PIX_CHAVE_PADRAO}`\n"
        f"*Banco:* {PIX_BANCO_PADRAO or 'confira no seu aplicativo bancário'}\n\n"
        "Você pode realizar a transferência pela chave acima ou escanear o QR Code enviado a esta conversa."
    )
    if qr_path.exists() and update.effective_chat:
        try:
            with open(qr_path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption="QR Code de doação ao Bode Andarilho",
                )
        except Exception as exc:
            logger.warning("Falha ao enviar QR de doação: %s", exc)

    await navegar_para(
        update,
        context,
        "Apoio Institucional > Doação",
        texto,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Falar com admin", callback_data="apoio_contato_admin")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="apoiar_menu")],
        ]),
    )


async def mostrar_publicidade_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else 0
    if get_nivel(user_id) != "3":
        await navegar_para(update, context, "Gestão de Apoios", "⛔ Área exclusiva para administradores.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]]))
        return

    txt = (
        "🤝 *Gestão de Apoios*\n\n"
        "Esta área concentra a governança do programa institucional.\n"
        "Os dados financeiros e de exibição são baseados em registros reais de exposição.\n\n"
        "Meta operacional sugerida: composição de parcerias para ~R$ 1.000/mês sem aumentar intrusão visual."
    )
    await navegar_para(update, context, "Gestão de Apoios", txt, InlineKeyboardMarkup([[InlineKeyboardButton("🤝 Ver apoiadores", callback_data="apoio_ver_apoiadores")], [InlineKeyboardButton("🔙 Voltar ao admin", callback_data="area_admin")]]))


def registrar_handlers_apoio(application):
    application.add_handler(CommandHandler("apoiar", cmd_apoiar))
    application.add_handler(CallbackQueryHandler(cmd_apoiar, pattern="^apoiar_menu$"))
    application.add_handler(CallbackQueryHandler(mostrar_apoiadores, pattern="^apoio_ver_apoiadores$"))
    application.add_handler(CallbackQueryHandler(falar_com_admin, pattern="^apoio_contato_admin$"))
    application.add_handler(CallbackQueryHandler(mostrar_doacao, pattern="^apoio_doar$"))
    application.add_handler(CallbackQueryHandler(mostrar_publicidade_admin, pattern="^admin_publicidade$"))


def obter_texto_patrocinio() -> str:
    return "\n\n_Apoio institucional: sua marca pode apoiar a manutenção do Bode Andarilho._"
