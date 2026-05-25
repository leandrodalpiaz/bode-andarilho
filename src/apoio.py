# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

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
TIPO_RODAPE_DIPLOMA = "rodape_diploma"

_FREQ_IA_MOD = 3



_CACHE_TTL_SEG = int(os.getenv("APOIO_CACHE_TTL_SEG", "180") or "180")
_ROWS_CACHE: Dict[str, Tuple[float, List[Dict]]] = {}


def _webapp_apoios_url(suffix: str = "") -> str:
    raw = (os.getenv("RENDER_EXTERNAL_URL", "") or "").strip().rstrip("/")
    lowered = raw.lower()
    if not raw or not lowered.startswith("https://") or "example.com" in lowered or "seu-app.onrender.com" in lowered:
        raw = "http://localhost:8000"
    return f"{raw}/webapp/apoios{suffix}"


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
    logo_url: str
    imagem_url: str
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


def _fetch_rows_cached(table: str, filters: Optional[List[Tuple[str, str, object]]] = None) -> List[Dict]:
    key = repr((table, filters or []))
    cached = _ROWS_CACHE.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL_SEG:
        return list(cached[1])
    rows = _fetch_rows(table, filters)
    _ROWS_CACHE[key] = (time.time(), list(rows))
    return rows


def buscar_apoiadores_ativos() -> List[Dict]:
    return _fetch_rows_cached("apoiadores", [("eq", "status", "ativo")])


def buscar_contratos_vigentes() -> List[Dict]:
    today = _today_iso()
    return _fetch_rows_cached(
        "apoios_contratos",
        [("eq", "status", "ativo"), ("lte", "data_inicio", today), ("gte", "data_fim", today)],
    )


def buscar_criativos_ativos(tipo_posicionamento: str = "") -> List[Dict]:
    hoje = _today_iso()
    rows = _fetch_rows_cached("apoios_criativos", [("eq", "status", "ativo")])
    ativos = []
    for row in rows:
        if tipo_posicionamento and str(row.get("tipo_posicionamento") or "") != tipo_posicionamento:
            continue
        inicio = str(row.get("data_inicio") or "")
        fim = str(row.get("data_fim") or "")
        if inicio and inicio > hoje:
            continue
        if fim and fim < hoje:
            continue
        ativos.append(row)
    return sorted(ativos, key=lambda x: int(x.get("prioridade") or 1), reverse=True)


def _criativo_por_apoiador(tipo_posicionamento: str) -> Dict[str, Dict]:
    return {
        str(c.get("apoiador_id")): c
        for c in buscar_criativos_ativos(tipo_posicionamento)
        if c.get("apoiador_id")
    }


def selecionar_criativo_apoio(tipo_posicionamento: str) -> Optional[Dict]:
    elegiveis = _listar_elegiveis(tipo_posicionamento)
    if elegiveis:
        escolhido = _weighted_pick(elegiveis, 1)[0]
        return escolhido.__dict__
    criativos = buscar_criativos_ativos(tipo_posicionamento)
    return criativos[0] if criativos else None


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
        TIPO_RODAPE_DIPLOMA: "limite_rodape_mes",
    }.get(tipo_exibicao, "")


def _categoria_peso(cat: str) -> int:
    return {"master": 10, "destaque": 6, "institucional": 3, "amigo_projeto": 1}.get((cat or "").lower(), 1)


def _listar_elegiveis(tipo_exibicao: str) -> List[ApoiadorElegivel]:
    apoiadores = {a.get("id"): a for a in buscar_apoiadores_ativos() if a.get("id")}
    contratos = buscar_contratos_vigentes()
    configs = {c.get("apoiador_id"): c for c in _fetch_rows_cached("apoios_config") if c.get("apoiador_id")}
    criativos_por_apoiador = _criativo_por_apoiador(tipo_exibicao)

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
        if tipo_exibicao == TIPO_RODAPE_DIPLOMA and not bool(cfg.get("permite_rodape")):
            continue

        limite_col = _limite_key(tipo_exibicao)
        limite = int(cfg.get(limite_col) or 0)
        if limite > 0 and _contar_exibicoes_mes(aid, tipo_exibicao) >= limite:
            continue

        ap = apoiadores[aid]
        criativo = criativos_por_apoiador.get(str(aid), {})
        texto = str(criativo.get("texto") or ap.get("texto_curto") or "").strip()
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
                link_publico=str(criativo.get("link_url") or ap.get("link_publico") or "").strip(),
                logo_url=str(criativo.get("imagem_url") or ap.get("logo_url") or "").strip(),
                imagem_url=str(criativo.get("imagem_url") or ap.get("imagem_publicidade_url") or "").strip(),
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
        logo_path = BRANDING_DIR / "sponsor_construtorasalomao.png"
        pick = logo_path if logo_path.exists() else None
        if not pick:
            placeholders = [
                BRANDING_DIR / "sponsor_placeholder_1.png",
                BRANDING_DIR / "sponsor_placeholder_2.png",
                BRANDING_DIR / "sponsor_placeholder_3.png",
            ]
            existentes = [p for p in placeholders if p.exists()]
            pick = random.choice(existentes) if existentes else None

        return {
            "apoiador_id": "placeholder",
            "contrato_id": "",
            "nome": "Construtora Salomão",
            "logo_path": str(pick) if pick else None,
        }
    escolhido = _weighted_pick(elegiveis, 1)[0]
    return {
        "apoiador_id": escolhido.apoiador_id,
        "contrato_id": escolhido.contrato_id,
        "nome": escolhido.nome,
        "logo_url": escolhido.logo_url,
    }


def selecionar_apoiadores_para_confirmados(limite: int = 2) -> List[Dict]:
    elegiveis = _listar_elegiveis(TIPO_CONF)
    picks = [x.__dict__ for x in _weighted_pick(elegiveis, limite)]
    if picks:
        return picks
    
    opcoes = [
        {
            "apoiador_id": "placeholder",
            "contrato_id": "",
            "nome": "Restaurante Ágape Fraterno",
            "texto_curto": "Sabor, tradição e atendimento impecável para os seus melhores momentos em família ou de negócios.",
            "logo_url": str(BRANDING_DIR / "sponsor_agapefraterno.png") if (BRANDING_DIR / "sponsor_agapefraterno.png").exists() else "",
        },
        {
            "apoiador_id": "placeholder2",
            "contrato_id": "",
            "nome": "O seu negócio em destaque aqui",
            "texto_curto": "Assim como você parou para ler esta mensagem, outros Irmãos também leriam sobre a sua empresa. Apoie o Bode Andarilho e ocupe este espaço.",
            "logo_url": "",
        }
    ]
    random.shuffle(opcoes)
    return opcoes[:limite]


def selecionar_apoiadores_para_ia(limite: int = 2) -> List[Dict]:
    elegiveis = _listar_elegiveis(TIPO_IA)
    picks = [x.__dict__ for x in _weighted_pick(elegiveis, limite)]
    if picks:
        return picks
    return [
        {
            "apoiador_id": "placeholder",
            "contrato_id": "",
            "nome": "Clínica do Mestre",
            "texto_curto": "Cuidado, prevenção e tecnologia avançada a favor da sua saúde e do seu bem-estar.",
            "logo_url": str(BRANDING_DIR / "sponsor_clinicamestre.png") if (BRANDING_DIR / "sponsor_clinicamestre.png").exists() else "",
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


def _admin_apoio(user_id: int) -> bool:
    return get_nivel(user_id) == "3"


def _money(v) -> float:
    try:
        return float(str(v or "0").replace(",", "."))
    except Exception:
        return 0.0


def _parse_bool_token(v: str) -> bool:
    return str(v or "").strip().lower() in {"1", "s", "sim", "true", "on", "ativo"}


def _apoio_stats() -> Dict[str, object]:
    apoiadores = _fetch_rows("apoiadores")
    contratos = _fetch_rows("apoios_contratos")
    exibicoes = _fetch_rows("apoios_exibicoes")
    hoje = _today_iso()
    ativos = [a for a in apoiadores if str(a.get("status") or "").lower() == "ativo"]
    contratos_ativos = [
        c for c in contratos
        if str(c.get("status") or "").lower() == "ativo"
        and str(c.get("data_inicio") or "") <= hoje
        and str(c.get("data_fim") or "") >= hoje
    ]
    pausados = [c for c in contratos if str(c.get("status") or "").lower() in {"pausado", "inadimplente"}]
    vencidos = [c for c in contratos if str(c.get("status") or "").lower() == "vencido" or str(c.get("data_fim") or "") < hoje]
    valor = sum(_money(c.get("valor_contribuicao")) for c in contratos_ativos)
    por_tipo: Dict[str, int] = {}
    for e in exibicoes:
        tipo = str(e.get("tipo_exibicao") or "sem_tipo")
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
    return {
        "apoiadores": apoiadores,
        "ativos": ativos,
        "contratos": contratos,
        "contratos_ativos": contratos_ativos,
        "pausados": pausados,
        "vencidos": vencidos,
        "valor": valor,
        "por_tipo": por_tipo,
    }


def _texto_gestao_apoios() -> str:
    stats = _apoio_stats()
    por_tipo = stats["por_tipo"] or {}
    linhas_tipo = "\n".join(f"- {k}: {v}" for k, v in sorted(por_tipo.items())) or "- sem exibições registradas"
    return (
        "🤝 *Gestão de Apoios*\n\n"
        f"Apoiadores cadastrados: *{len(stats['apoiadores'])}*\n"
        f"Apoiadores ativos: *{len(stats['ativos'])}*\n"
        f"Contratos ativos: *{len(stats['contratos_ativos'])}*\n"
        f"Contratos pausados/inadimplentes: *{len(stats['pausados'])}*\n"
        f"Contratos vencidos: *{len(stats['vencidos'])}*\n"
        f"Receita mensal estimada: *R$ {stats['valor']:.2f}*\n\n"
        "*Exibições registradas por tipo:*\n"
        f"{linhas_tipo}\n\n"
        "Use os menus abaixo para cadastrar apoiadores, contratos e regras de exibição."
    )


def _teclado_gestao_apoios() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤝 Apoiadores", web_app=WebAppInfo(url=_webapp_apoios_url("/apoiadores"))),
            InlineKeyboardButton("📋 Contratos", web_app=WebAppInfo(url=_webapp_apoios_url("/contratos")))
        ],
        [
            InlineKeyboardButton("💰 Financeiro", web_app=WebAppInfo(url=_webapp_apoios_url("/financeiro"))),
            InlineKeyboardButton("🎨 Criativos", web_app=WebAppInfo(url=_webapp_apoios_url("/criativos")))
        ],
        [InlineKeyboardButton("🧾 Gerar comprovante", callback_data="admin_apoio_comprovante_inicio")],
        [InlineKeyboardButton("🔙 Voltar ao admin", callback_data="area_admin")],
    ])


async def admin_apoio_listar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else 0
    if not _admin_apoio(user_id):
        return
    apoiadores = buscar_apoiadores_ativos()
    todos = _fetch_rows("apoiadores")
    contratos = buscar_contratos_vigentes()
    contrato_por_apoiador = {str(c.get("apoiador_id")): c for c in contratos}
    linhas = ["🤝 *Apoiadores cadastrados*\n"]
    base = todos[:30]
    if not base:
        linhas.append("Nenhum apoiador cadastrado.")
    for a in base:
        c = contrato_por_apoiador.get(str(a.get("id")))
        valor = f"R$ {_money((c or {}).get('valor_contribuicao')):.2f}" if c else "sem contrato vigente"
        linhas.append(
            f"• `{a.get('id')}`\n"
            f"  *{a.get('nome','Apoiador')}* | {a.get('status','')}\n"
            f"  {a.get('segmento') or 'sem segmento'} | {valor}"
        )
    linhas.append(f"\nAtivos com contrato vigente: {len(apoiadores)}")
    await navegar_para(update, context, "Gestão de Apoios > Lista", "\n".join(linhas), _teclado_gestao_apoios())


async def admin_apoio_comprovante_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass
    user_id = update.effective_user.id if update.effective_user else 0
    if not _admin_apoio(user_id):
        return
    
    apoiadores = _fetch_rows("apoiadores")
    if not apoiadores:
        await navegar_para(update, context, "Gerar Comprovante", "Nenhum apoiador cadastrado no sistema.", _teclado_gestao_apoios())
        return
    
    botoes = []
    linha = []
    for a in apoiadores:
        linha.append(InlineKeyboardButton(a.get("nome", "Apoiador"), callback_data=f"admin_apoio_comp_apoiador:{a.get('id')}"))
        if len(linha) == 2:
            botoes.append(linha)
            linha = []
    if linha:
        botoes.append(linha)
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="admin_publicidade")])
    
    await navegar_para(
        update,
        context,
        "Gerar Comprovante",
        "Selecione o apoiador para gerar o comprovante:",
        InlineKeyboardMarkup(botoes)
    )


async def admin_apoio_comp_apoiador(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    try:
        await q.answer()
    except Exception:
        pass
    user_id = update.effective_user.id if update.effective_user else 0
    if not _admin_apoio(user_id):
        return
    
    apoiador_id = q.data.split(":")[1]
    apoiador_list = _fetch_rows("apoiadores", [("eq", "id", apoiador_id)])
    if not apoiador_list:
        await navegar_para(update, context, "Gerar Comprovante", "Apoiador não encontrado.", _teclado_gestao_apoios())
        return
    apoiador = apoiador_list[0]
    
    pagamentos = _fetch_rows("apoios_pagamentos", [("eq", "apoiador_id", apoiador_id)])
    if not pagamentos:
        await navegar_para(update, context, "Gerar Comprovante", f"Nenhum pagamento registrado no financeiro para *{apoiador.get('nome')}*.", _teclado_gestao_apoios())
        return
        
    botoes = []
    pagamentos.sort(key=lambda x: x.get("competencia", ""), reverse=True)
    for p in pagamentos[:10]:
        status_label = "Pago" if p.get("status") == "pago" else "Pendente"
        botoes.append([InlineKeyboardButton(f"Comp. {p.get('competencia')} ({status_label})", callback_data=f"admin_apoio_comp_gerar:{apoiador_id}:{p.get('id')}")])
        
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="admin_apoio_comprovante_inicio")])
    
    await navegar_para(
        update,
        context,
        "Gerar Comprovante",
        f"Selecione a competência do comprovante para *{apoiador.get('nome')}*:",
        InlineKeyboardMarkup(botoes)
    )


async def admin_apoio_comp_gerar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    try:
        await q.answer()
    except Exception:
        pass
    user_id = update.effective_user.id if update.effective_user else 0
    if not _admin_apoio(user_id):
        return
        
    partes = q.data.split(":")
    apoiador_id = partes[1]
    pagamento_id = partes[2]
    
    apoiador_list = _fetch_rows("apoiadores", [("eq", "id", apoiador_id)])
    pagamento_list = _fetch_rows("apoios_pagamentos", [("eq", "id", pagamento_id)])
    
    if not apoiador_list or not pagamento_list:
        await navegar_para(update, context, "Gerar Comprovante", "Dados não encontrados.", _teclado_gestao_apoios())
        return
        
    a = apoiador_list[0]
    p = pagamento_list[0]
    
    status_icon = "✅" if p.get("status") == "pago" else "⚠️" if p.get("status") == "pendente" else "ℹ️"
    status_text = str(p.get("status") or "").upper()
    val_prev = float(p.get("valor_previsto") or 0.0)
    val_pago = float(p.get("valor_pago") or 0.0)
    
    def format_date(iso_str):
        if not iso_str:
            return "N/A"
        try:
            parts = iso_str.split("-")
            if len(parts) == 3:
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
        except Exception:
            pass
        return iso_str
        
    dt_pag = format_date(p.get("data_pagamento"))
    forma = p.get("forma_pagamento") or "N/A"
    
    texto = (
        "🧾 *COMPROVANTE DE APOIO INSTITUCIONAL*\n\n"
        f"*Apoiador:* {a.get('nome')}\n"
        f"*Responsável:* {a.get('responsavel_nome') or 'N/A'}\n"
        f"*Competência:* {p.get('competencia')}\n"
        f"*Valor Previsto:* R$ {val_prev:.2f}\n"
        f"*Valor Pago:* R$ {val_pago:.2f}\n"
        f"*Status:* {status_icon} {status_text}\n"
        f"*Data Pagamento:* {dt_pag}\n"
        f"*Forma:* {forma}\n\n"
        "---\n"
        "_Bode Andarilho — Publicidade e Apoios_"
    )
    
    await navegar_para(update, context, "Comprovante Gerado", texto, _teclado_gestao_apoios())


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
    criativos_tela = _criativo_por_apoiador(TIPO_TELA)

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
            criativo = criativos_tela.get(str(a.get("id")), {})
            tc = str(criativo.get("texto") or a.get("texto_curto") or "").strip()
            if tc:
                texto += f" — {tc}"
            texto += "\n"

    botoes = []
    for a in ativos:
        criativo = criativos_tela.get(str(a.get("id")), {})
        link = str(criativo.get("link_url") or a.get("link_publico") or "").strip()
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

    user_id = update.effective_user.id if update.effective_user else 0
    if get_nivel(user_id) != "3":
        await navegar_para(
            update,
            context,
            "Apoio Institucional",
            "🤝 *Apoio Institucional*\n\nA funcionalidade de Apoio Institucional está em fase de preparação e estará disponível em breve para todos os Irmãos.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]]),
        )
        return

    texto = (
        "🤝 *REDE DE APOIO DO BODE ANDARILHO*\n\n"
        "Ajude a manter o nosso bot no ar, incentivando as visitações entre as Oficinas, e aproveite para divulgar o seu trabalho para a nossa comunidade. Escolha a sua faixa de apoio:\n\n"
        "Para conhecer mais sobre a finalidade de cada plano, valores e a disponibilidade de vagas, acione o botão abaixo."
    )
    await navegar_para(
        update,
        context,
        "Apoio Institucional",
        texto,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Conhecer os Planos", callback_data="apoio_ver_planos")],
            [InlineKeyboardButton("🤝 Ver apoiadores", callback_data="apoio_ver_apoiadores")],
            [InlineKeyboardButton("💬 Falar com admin", callback_data="apoio_contato_admin")],
            *([[InlineKeyboardButton("💝 Doar ao projeto", callback_data="apoio_doar")]] if doacoes_ativas() else []),
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")],
        ]),
    )


async def mostrar_detalhes_planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass

    user_id = update.effective_user.id if update.effective_user else 0
    if get_nivel(user_id) != "3":
        return

    texto = (
        "🤝 *REDE DE APOIO DO BODE ANDARILHO*\n\n"
        "Ajude a manter o nosso bot no ar, incentivando as visitações entre as Oficinas, e aproveite para divulgar o seu trabalho para a nossa comunidade. Escolha a sua faixa de apoio:\n\n"
        "🔹 *1. Amigo do Projeto — R$ 33,00 / mês* (ou R$ 330,00/ano)\n"
        "• *Propósito:* Apoio de Irmão para Irmão. Ideal para contribuição individual e simples para cobrir os custos básicos da tecnologia.\n"
        "• *Onde aparece:* Nome e link na \"Tela de Apoiadores\" do Mini App.\n\n"
        "🔹 *2. Institucional — R$ 60,00 / mês* (ou R$ 600,00/ano) — _[Restam 5 vagas]_\n"
        "• *Propósito:* Ideal para o profissional autônomo ou pequeno empreendedor que quer fortalecer a causa e deixar seus serviços à disposição dos Irmãos.\n"
        "• *Onde aparece:* Tela de Apoiadores, inserção nas menções da IA e rodapé de diplomas gerados.\n\n"
        "🔹 *3. Destaque — R$ 120,00 / mês* (ou R$ 1.200,00/ano) — _[Restam 3 vagas]_\n"
        "• *Propósito:* Para quem quer estar onde o movimento acontece. Ideal para empresas que apoiam ativamente a intervisitação e querem presença diária.\n"
        "• *Onde aparece:* Benefícios anteriores + texto de apoio discreto no rodapé da lista de confirmados das sessões.\n\n"
        "👑 *4. Master — R$ 250,00 / mês* (ou R$ 2.500,00/ano) — _[Restam 2 vagas]_\n"
        "• *Propósito:* Para os grandes benfeitores. Ideal para empresas que compreendem o impacto do sistema na modernização das Lojas e querem máxima associação à evolução do projeto.\n"
        "• *Onde aparece:* Prioridade nos sorteios de espaços + todos os benefícios + exibição da logo nos cards/flyers de divulgação dos eventos."
    )
    await navegar_para(
        update,
        context,
        "Apoio Institucional > Planos",
        texto,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Falar com admin", callback_data="apoio_contato_admin")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="apoiar_menu")],
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

    await navegar_para(update, context, "Gestão de Apoios", _texto_gestao_apoios(), _teclado_gestao_apoios())


def registrar_handlers_apoio(application):
    application.add_handler(CommandHandler("apoiar", cmd_apoiar))
    application.add_handler(CallbackQueryHandler(cmd_apoiar, pattern="^apoiar_menu$"))
    application.add_handler(CallbackQueryHandler(mostrar_apoiadores, pattern="^apoio_ver_apoiadores$"))
    application.add_handler(CallbackQueryHandler(falar_com_admin, pattern="^apoio_contato_admin$"))
    application.add_handler(CallbackQueryHandler(mostrar_doacao, pattern="^apoio_doar$"))
    application.add_handler(CallbackQueryHandler(mostrar_publicidade_admin, pattern="^admin_publicidade$"))
    application.add_handler(CallbackQueryHandler(admin_apoio_listar, pattern="^admin_apoio_listar$"))
    application.add_handler(CallbackQueryHandler(admin_apoio_comprovante_inicio, pattern="^admin_apoio_comprovante_inicio$"))
    application.add_handler(CallbackQueryHandler(admin_apoio_comp_apoiador, pattern="^admin_apoio_comp_apoiador:"))
    application.add_handler(CallbackQueryHandler(admin_apoio_comp_gerar, pattern="^admin_apoio_comp_gerar:"))
    application.add_handler(CallbackQueryHandler(mostrar_detalhes_planos, pattern="^apoio_ver_planos$"))


def obter_texto_patrocinio() -> str:
    return "\n\n_Apoio: Magna Advogados — Tradição, ética e excelência na proteção do seu patrimônio._"
