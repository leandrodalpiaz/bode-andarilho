# src/ia_multinivel.py
# ============================================
# BODE ANDARILHO — CAMADA DE IA ASSISTIVA MULTINÍVEL
# ============================================
#
# Motor de classificação de intenção, extração de entidades e
# despacho para fluxos existentes, organizado por perfil (1/2/3).
#
# Regras:
#   - NÃO grava/lê Supabase diretamente: sempre delega para handlers já existentes.
#   - NÃO cria fluxos paralelos, endpoints nem tabelas.
#   - Toda ação sensível exige preview / confirmação.
#   - Ambiguidade → pedir desambiguação mínima; nunca inferir sem segurança.
# ============================================

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================
# CONTRATO INTERNO DE RESULTADO
# ============================================

@dataclass
class IAResult:
    """Contrato de saída da camada assistiva multinível."""
    intent: str = ""                # intent classificada
    confidence: str = "none"        # "high", "medium", "low", "none"
    entities: Dict[str, str] = field(default_factory=dict)
    target_callback: str = ""       # callback do handler existente a invocar
    preview_text: str = ""          # texto de preview/resposta para o usuário
    needs_confirmation: bool = False
    blocked: bool = False
    block_reason: str = ""
    disambiguation: str = ""        # pergunta de desambiguação, se houver
    tone: str = "acolhedor"         # "acolhedor" | "objetivo" | "direto"


# ============================================
# NORMALIZAÇÃO DE TEXTO
# ============================================

def _norm(value: str) -> str:
    texto = unicodedata.normalize("NFKD", str(value or ""))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


# ============================================
# EXTRAÇÃO DE ENTIDADES — DATA
# ============================================

_DIAS_SEMANA = {
    "segunda": 0, "segunda-feira": 0, "seg": 0,
    "terca": 1, "terca-feira": 1, "ter": 1,
    "quarta": 2, "quarta-feira": 2, "qua": 2,
    "quinta": 3, "quinta-feira": 3, "qui": 3,
    "sexta": 4, "sexta-feira": 4, "sex": 4,
    "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}

_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4,
    "mai": 5, "jun": 6, "jul": 7, "ago": 8,
    "set": 9, "out": 10, "nov": 11, "dez": 12,
}


def _extrair_data(texto: str) -> Optional[str]:
    """Extrai data no formato DD/MM/AAAA de linguagem natural."""
    t = _norm(texto)

    # Formato DD/MM/AAAA ou DD/MM
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yyyy = int(m.group(3)) if m.group(3) else datetime.now().year
        if yyyy < 100:
            yyyy += 2000
        try:
            dt = datetime(yyyy, mm, dd)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass

    # "próxima quarta", "essa sexta", "na quinta"
    for dia_nome, dia_num in _DIAS_SEMANA.items():
        if dia_nome in t:
            hoje = datetime.now()
            diff = (dia_num - hoje.weekday()) % 7
            if diff == 0:
                diff = 7  # "próxima" = semana que vem
            if "proxima" in t or "proximo" in t:
                if diff == 0:
                    diff = 7
            dt = hoje + timedelta(days=diff)
            return dt.strftime("%d/%m/%Y")

    # "amanha"
    if "amanha" in t:
        dt = datetime.now() + timedelta(days=1)
        return dt.strftime("%d/%m/%Y")

    # "hoje"
    if "hoje" in t:
        return datetime.now().strftime("%d/%m/%Y")

    # "dia 25" or "dia 25 de abril"
    m_dia = re.search(r"dia (\d{1,2})(?:\s+de\s+(\w+))?", t)
    if m_dia:
        dd = int(m_dia.group(1))
        mes_str = m_dia.group(2)
        mm = _MESES.get(_norm(mes_str), None) if mes_str else datetime.now().month
        yyyy = datetime.now().year
        if mm:
            try:
                dt = datetime(yyyy, mm, dd)
                if dt < datetime.now():
                    dt = datetime(yyyy + 1, mm, dd)
                return dt.strftime("%d/%m/%Y")
            except ValueError:
                pass

    return None


# ============================================
# EXTRAÇÃO DE ENTIDADES — HORA
# ============================================

def _extrair_hora(texto: str) -> Optional[str]:
    """Extrai horário HH:MM de linguagem natural."""
    t = _norm(texto)

    # HH:MM ou HHhMM ou HH:MM:SS
    m = re.search(r"(\d{1,2})[h:](\d{2})(?::(\d{2}))?", t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"

    # "as 19", "19 horas"
    m2 = re.search(r"(?:as\s+)?(\d{1,2})\s*(?:horas?|hrs?)", t)
    if m2:
        hh = int(m2.group(1))
        if 0 <= hh <= 23:
            return f"{hh:02d}:00"

    return None


# ============================================
# EXTRAÇÃO DE ENTIDADES — GRAU
# ============================================

_GRAUS_MAP = {
    "aprendiz": "Aprendiz",
    "companheiro": "Companheiro",
    "mestre": "Mestre",
    "mestre instalado": "Mestre Instalado",
    "mi": "Mestre Instalado",
}


def _extrair_grau(texto: str) -> Optional[str]:
    t = _norm(texto)
    # Ordem longa → curta para evitar falso match de "mestre" em "mestre instalado"
    for chave in ("mestre instalado", "mi", "companheiro", "aprendiz", "mestre"):
        if chave in t:
            return _GRAUS_MAP[chave]
    return None


# ============================================
# EXTRAÇÃO DE ENTIDADES — ÁGAPE
# ============================================

def _extrair_agape(texto: str) -> Tuple[Optional[str], Optional[str]]:
    """Retorna (tem_agape, tipo_agape) ou (None, None)."""
    t = _norm(texto)
    if "sem agape" in t or "sem ágape" in t:
        return ("nao", "")
    if "agape pago" in t or "ágape pago" in t:
        return ("sim", "pago")
    if "agape gratuito" in t or "ágape gratuito" in t:
        return ("sim", "gratuito")
    if "com agape" in t or "com ágape" in t:
        return ("sim", "")
    return (None, None)


# ============================================
# EXTRAÇÃO DE ENTIDADES — CAMPOS CADASTRAIS
# ============================================

_CAMPOS_CADASTRAIS_MAP = {
    "nome": "Nome",
    "nome civil": "Nome",
    "data de nascimento": "Data de nascimento",
    "nascimento": "Data de nascimento",
    "aniversario": "Data de nascimento",
    "grau": "Grau",
    "rito": "Rito",
    "potencia": "Potência",
    "oriente": "Oriente",
    "loja": "Loja",
    "numero da loja": "Número da loja",
    "numero loja": "Número da loja",
}

# Campos permitidos no fluxo assistido comum
CAMPOS_EDITAVEIS_IA = {
    "Nome", "Data de nascimento", "Grau", "Rito",
    "Potência", "Oriente", "Loja", "Número da loja",
}

# Campos sensíveis que NÃO podem ser editados pela IA
CAMPOS_SENSÍVEIS = {
    "Nivel", "Status", "Cargo", "Mestre Instalado", "Venerável Mestre",
}


def _extrair_campo_cadastral(texto: str) -> Optional[str]:
    """Identifica qual campo cadastral o usuário quer alterar."""
    t = _norm(texto)
    for chave, campo in _CAMPOS_CADASTRAIS_MAP.items():
        if chave in t:
            return campo
    return None


def _extrair_nome_alvo(texto: str) -> Optional[str]:
    """Tenta extrair nome do membro mencionado no texto (heurística simples)."""
    t = _norm(texto)
    # "do irmao João", "do João", "de João", "membro João"
    patterns = [
        r"(?:do\s+irmao|do\s+ir\.|do|de|membro|irmao)\s+([A-Z][a-záéíóúãõ]+(?:\s+[A-Z][a-záéíóúãõ]+)*)",
    ]
    # Work on original texto (case preserved) for name extraction
    original = (texto or "").strip()
    for pat in patterns:
        m = re.search(pat, original, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


# ============================================
# CLASSIFICADOR MULTINÍVEL
# ============================================

def classificar_intencao_multinivel(
    texto: str,
    nivel: str,
    lojas_do_secretario: Optional[List[Dict[str, Any]]] = None,
) -> IAResult:
    """
    Classifica intenção do texto livre em função do perfil do ator.

    Retorna IAResult com intent, entidades, callback de destino e tom.
    """
    t = _norm(texto)
    result = IAResult()

    # Tom por perfil
    if nivel == "1":
        result.tone = "acolhedor"
    elif nivel == "2":
        result.tone = "objetivo"
    else:
        result.tone = "direto"

    # ── NÍVEL 2/3: Criação de evento por linguagem natural ──────────
    if nivel in ("2", "3") and _parece_criacao_evento(t):
        return _classificar_criacao_evento(texto, nivel, result, lojas_do_secretario)

    # ── QUALQUER NÍVEL: Edição cadastral ────────────────────────────
    if _parece_edicao_cadastral(t):
        return _classificar_edicao_cadastral(texto, nivel, result, lojas_do_secretario)

    # ── NÍVEL 3: Comandos admin simples ─────────────────────────────
    if nivel == "3" and _parece_comando_admin(t):
        return _classificar_comando_admin(t, result)

    # ── NÍVEL 1: Navegação assistida ────────────────────────────────
    nav = _classificar_navegacao(t, nivel)
    if nav:
        return nav

    # Sem match seguro → devolver para o fallback YAML base
    return result


# ============================================
# DETECÇÃO DE INTENÇÃO — CRIAÇÃO DE EVENTO
# ============================================

_GATILHOS_CRIACAO_EVENTO = [
    "criar evento", "criar sessao", "cadastrar sessao", "cadastrar evento",
    "nova sessao", "novo evento", "agendar sessao", "agendar evento",
    "publicar sessao", "marcar sessao",
]


def _parece_criacao_evento(t: str) -> bool:
    return any(g in t for g in _GATILHOS_CRIACAO_EVENTO)


def _classificar_criacao_evento(
    texto: str,
    nivel: str,
    result: IAResult,
    lojas_do_secretario: Optional[List[Dict[str, Any]]] = None,
) -> IAResult:
    """Extrai entidades de um pedido de criação de evento e monta rascunho."""
    result.intent = "criar_evento_natural"
    result.confidence = "high"
    result.needs_confirmation = True

    # Extrair entidades
    data = _extrair_data(texto)
    hora = _extrair_hora(texto)
    grau = _extrair_grau(texto)
    agape_tem, agape_tipo = _extrair_agape(texto)

    entities: Dict[str, str] = {}
    if data:
        entities["data"] = data
    if hora:
        entities["hora"] = hora
    if grau:
        entities["grau"] = grau
    if agape_tem is not None:
        entities["agape"] = agape_tem
    if agape_tipo:
        entities["agape_tipo"] = agape_tipo

    if nivel == "2":
        _aplicar_loja_em_entities(_obter_loja_padrao_secretario(lojas_do_secretario), entities)
    else:
        # Admin: usa a loja apenas se ela vier explicitamente na mensagem.
        loja_match = _match_loja_no_texto(texto, lojas_do_secretario)
        _aplicar_loja_em_entities(loja_match, entities)

    # Extrair campos soltos do texto: tipo_sessao, rito, potencia, traje, observacoes
    _extrair_campos_evento_extras(texto, entities)

    result.entities = entities

    # Verificar campos obrigatórios faltantes
    faltantes = _campos_evento_faltantes(entities)

    if faltantes:
        result.confidence = "medium"
        result.preview_text = _montar_preview_evento_parcial(entities, faltantes)
        result.disambiguation = _perguntar_campos_faltantes(faltantes, nivel)
        result.target_callback = ""  # aguarda mais dados
    else:
        result.preview_text = _montar_preview_evento_completo(entities)
        result.target_callback = "ia_confirmar_evento"

    return result


def _obter_loja_padrao_secretario(
    lojas_do_secretario: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if not lojas_do_secretario:
        return None
    return lojas_do_secretario[0]


def _aplicar_loja_em_entities(
    loja: Optional[Dict[str, Any]],
    entities: Dict[str, str],
) -> None:
    if not loja:
        return
    entities["nome_loja"] = loja.get("Nome da Loja", "")
    entities["numero_loja"] = str(loja.get("Número", ""))
    entities["oriente"] = loja.get("Oriente da Loja", "") or loja.get("Oriente", "")
    entities["rito"] = loja.get("Rito", "")
    entities["potencia"] = loja.get("Potência", "")
    entities["endereco"] = loja.get("Endereço", "")
    entities["loja_id"] = str(loja.get("ID") or loja.get("id") or "")


def _match_loja_no_texto(
    texto: str,
    lojas: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Busca uma loja pelo nome no texto (fuzzy simples)."""
    if not lojas:
        return None
    t = _norm(texto)
    melhor: Optional[Dict[str, Any]] = None
    melhor_len = 0
    for loja in lojas:
        nome = _norm(loja.get("Nome da Loja", ""))
        if nome and nome in t and len(nome) > melhor_len:
            melhor = loja
            melhor_len = len(nome)
    return melhor


_CAMPOS_EVENTO_OBRIGATORIOS = ["data", "hora", "nome_loja"]


def _campos_evento_faltantes(entities: Dict[str, str]) -> List[str]:
    faltantes = []
    for campo in _CAMPOS_EVENTO_OBRIGATORIOS:
        if not entities.get(campo):
            faltantes.append(campo)
    return faltantes


_NOMES_CAMPO_AMIGAVEL = {
    "data": "data do evento (ex: 25/04/2026 ou próxima quarta)",
    "hora": "horário (ex: 19:30)",
    "nome_loja": "nome da loja",
}


def _perguntar_campos_faltantes(faltantes: List[str], nivel: str = "") -> str:
    if not faltantes:
        return ""
    if nivel == "3" and faltantes == ["nome_loja"]:
        return "Como você não possui loja vinculada, informe a loja do evento."
    partes = [_NOMES_CAMPO_AMIGAVEL.get(c, c) for c in faltantes]
    if nivel == "3" and "nome_loja" in faltantes:
        partes = [
            "loja do evento" if campo == "nome_loja" else _NOMES_CAMPO_AMIGAVEL.get(campo, campo)
            for campo in faltantes
        ]
    if len(partes) == 1:
        return f"Para criar o evento, preciso saber: {partes[0]}."
    return "Para criar o evento, preciso saber:\n" + "\n".join(f"• {p}" for p in partes)


def _montar_preview_evento_parcial(entities: Dict[str, str], faltantes: List[str]) -> str:
    linhas = ["📝 *Rascunho do evento (parcial):*\n"]
    if entities.get("nome_loja"):
        numero = entities.get("numero_loja", "")
        num_fmt = f" {numero}" if numero and numero != "0" else ""
        linhas.append(f"🏛 Loja: {entities['nome_loja']}{num_fmt}")
    if entities.get("data"):
        linhas.append(f"📅 Data: {entities['data']}")
    if entities.get("hora"):
        linhas.append(f"🕕 Hora: {entities['hora']}")
    if entities.get("grau"):
        linhas.append(f"🔺 Grau: {entities['grau']}")
    if entities.get("rito"):
        linhas.append(f"📜 Rito: {entities['rito']}")
    if entities.get("agape"):
        agape_txt = "Sim" if entities["agape"] == "sim" else "Não"
        if entities.get("agape_tipo"):
            agape_txt += f" ({entities['agape_tipo'].capitalize()})"
        linhas.append(f"🍽 Ágape: {agape_txt}")
    return "\n".join(linhas)


def _montar_preview_evento_completo(entities: Dict[str, str]) -> str:
    numero = entities.get("numero_loja", "")
    num_fmt = f" {numero}" if numero and numero != "0" else ""
    agape_txt = "Não"
    if entities.get("agape") == "sim":
        agape_txt = "Sim"
        if entities.get("agape_tipo"):
            agape_txt += f" ({entities['agape_tipo'].capitalize()})"

    linhas = [
        "📝 *Rascunho do evento:*\n",
        f"🏛 *Loja:* {entities.get('nome_loja', '')}{num_fmt}",
        f"📅 *Data:* {entities.get('data', '')}",
        f"🕕 *Hora:* {entities.get('hora', '')}",
        f"📍 *Oriente:* {entities.get('oriente', '')}",
        f"🔺 *Grau:* {entities.get('grau', 'Aprendiz')}",
        f"📜 *Rito:* {entities.get('rito', '')}",
        f"⚜️ *Potência:* {entities.get('potencia', '')}",
        f"🍽 *Ágape:* {agape_txt}",
        f"🗺 *Endereço:* {entities.get('endereco', '')}",
    ]
    if entities.get("tipo_sessao"):
        linhas.append(f"🕯 *Tipo de sessão:* {entities['tipo_sessao']}")
    if entities.get("traje"):
        linhas.append(f"🎩 *Traje:* {entities['traje']}")
    if entities.get("observacoes"):
        linhas.append(f"📝 *Observações:* {entities['observacoes']}")
    linhas.append("\nConfirme para publicar ou edite os dados.")
    return "\n".join(linhas)


def _extrair_campos_evento_extras(texto: str, entities: Dict[str, str]) -> None:
    """Extrai campos opcionais de evento do texto."""
    t = _norm(texto)

    # Tipo de sessão
    tipos_sessao = {
        "sessao magna": "Magna", "magna": "Magna",
        "sessao ordinaria": "Ordinária", "ordinaria": "Ordinária",
        "sessao extraordinaria": "Extraordinária", "extraordinaria": "Extraordinária",
        "sessao branca": "Branca", "branca": "Branca",
        "sessao funebre": "Fúnebre", "funebre": "Fúnebre",
    }
    for chave, valor in tipos_sessao.items():
        if chave in t:
            entities.setdefault("tipo_sessao", valor)
            break

    # Traje
    trajes = {
        "traje escuro": "Escuro", "terno escuro": "Escuro", "escuro": "Escuro",
        "traje social": "Social", "social": "Social",
        "traje passeio": "Passeio", "passeio": "Passeio",
    }
    for chave, valor in trajes.items():
        if chave in t:
            entities.setdefault("traje", valor)
            break


# ============================================
# DETECÇÃO DE INTENÇÃO — EDIÇÃO CADASTRAL
# ============================================

_GATILHOS_EDICAO = [
    "alterar cadastro", "editar cadastro", "mudar cadastro",
    "alterar meu", "editar meu", "mudar meu",
    "alterar nome", "mudar nome", "editar nome",
    "alterar grau", "mudar grau", "editar grau",
    "alterar loja", "mudar loja", "editar loja",
    "alterar oriente", "mudar oriente",
    "alterar potencia", "mudar potencia",
    "alterar rito", "mudar rito",
    "alterar nascimento", "mudar nascimento",
    "alterar data de nascimento", "mudar data de nascimento",
    "alterar numero da loja", "mudar numero da loja",
    "corrigir cadastro", "retificar cadastro",
    "alterar cadastro do", "editar cadastro do",
    "editar membro", "alterar membro",
]


def _parece_edicao_cadastral(t: str) -> bool:
    return any(g in t for g in _GATILHOS_EDICAO)


def _classificar_edicao_cadastral(
    texto: str,
    nivel: str,
    result: IAResult,
    lojas_do_secretario: Optional[List[Dict[str, Any]]] = None,
) -> IAResult:
    """Interpreta pedido de edição cadastral com validação ator/alvo/campo/escopo."""
    result.intent = "editar_cadastro"
    result.needs_confirmation = True
    t = _norm(texto)

    # Identificar campo
    campo = _extrair_campo_cadastral(texto)
    if campo and campo in CAMPOS_SENSÍVEIS:
        result.blocked = True
        result.block_reason = "campo_sensivel"
        result.preview_text = (
            f"O campo *{campo}* só pode ser alterado pelo fluxo administrativo oficial, "
            "não pelo assistente. Posso te levar ao menu correto."
        )
        result.target_callback = "menu_principal"
        result.confidence = "high"
        return result

    # Identificar se é edição do próprio cadastro ou de outro membro
    eh_proprio = _parece_edicao_propria(t)
    nome_alvo = _extrair_nome_alvo(texto) if not eh_proprio else None

    if eh_proprio or not nome_alvo:
        # Edição do próprio cadastro — qualquer nível pode
        result.intent = "editar_cadastro_proprio"
        result.confidence = "high"
        result.target_callback = "editar_perfil"
        if campo and campo in CAMPOS_EDITAVEIS_IA:
            result.entities["campo"] = campo
            result.preview_text = f"Vou abrir a edição do seu campo *{campo}*."
        else:
            result.preview_text = "Vou abrir o menu de edição do seu cadastro."
        return result

    # Edição de outro membro
    if nivel == "1":
        result.blocked = True
        result.block_reason = "nivel_insuficiente"
        result.confidence = "high"
        result.preview_text = (
            "Membros comuns podem editar apenas o próprio cadastro. "
            "Posso te ajudar com isso?"
        )
        result.target_callback = "editar_perfil"
        return result

    # Nível 2 ou 3 editando outro membro
    result.intent = "editar_cadastro_membro"
    result.entities["nome_alvo"] = nome_alvo or ""
    if campo and campo in CAMPOS_EDITAVEIS_IA:
        result.entities["campo"] = campo

    if nivel == "2":
        # Secretário: precisa verificar escopo por loja
        result.entities["validar_escopo_loja"] = "sim"
        result.confidence = "medium"
        result.needs_confirmation = True
        result.preview_text = (
            f"Vou abrir a edição de membro. "
            f"Como secretário, posso editar membros vinculados à sua loja."
        )
        result.target_callback = "admin_editar_membro"
    else:
        # Admin: sem restrição de loja
        result.confidence = "high"
        result.preview_text = f"Vou abrir a edição do membro *{nome_alvo}*."
        result.target_callback = "admin_editar_membro"

    return result


def _parece_edicao_propria(t: str) -> bool:
    indicadores = [
        "meu cadastro", "meu perfil", "meu nome", "meu grau",
        "minha loja", "meu oriente", "minha potencia", "meu rito",
        "meu numero", "minha data", "meu nascimento",
        "alterar meu", "editar meu", "mudar meu",
        "corrigir meu", "retificar meu",
    ]
    return any(ind in t for ind in indicadores)


# ============================================
# DETECÇÃO DE INTENÇÃO — COMANDOS ADMIN SIMPLES
# ============================================

_ADMIN_COMMANDS = [
    (["area admin", "painel admin", "menu admin", "administracao"], "area_admin", "Vou abrir o Painel de Administração."),
    (["ver membros", "listar membros", "todos os membros"], "admin_ver_membros", "Vou listar os membros cadastrados."),
    (["promover secretario", "promover membro"], "admin_promover", "Vou abrir o fluxo de promoção de membro."),
    (["rebaixar secretario", "rebaixar membro"], "admin_rebaixar", "Vou abrir o fluxo de rebaixamento."),
    (["gerenciar lojas", "todas as lojas"], "menu_lojas", "Vou abrir o gerenciamento de lojas."),
    (["gerenciar eventos", "todos os eventos"], "meus_eventos", "Vou listar todos os eventos para gerenciamento."),
    (["cancelar evento"], "meus_eventos", "Vou abrir a lista de eventos. Selecione qual deseja cancelar."),
    (["configurar notificacoes", "notificacoes"], "menu_notificacoes", "Vou abrir as configurações de notificações."),
]


def _parece_comando_admin(t: str) -> bool:
    for gatilhos, _, _ in _ADMIN_COMMANDS:
        if any(g in t for g in gatilhos):
            return True
    return False


def _classificar_comando_admin(t: str, result: IAResult) -> IAResult:
    result.tone = "direto"
    for gatilhos, callback, resposta in _ADMIN_COMMANDS:
        if any(g in t for g in gatilhos):
            result.intent = f"admin_{callback}"
            result.confidence = "high"
            result.target_callback = callback
            result.preview_text = resposta
            return result
    return result


# ============================================
# DETECÇÃO DE INTENÇÃO — NAVEGAÇÃO ASSISTIDA (NÍVEL 1+)
# ============================================

_NAV_INTENTS = [
    # (gatilhos, callback, resposta_nivel1, resposta_outros, niveis_permitidos)
    (
        ["ver sessoes", "quais sessoes", "eventos da semana", "proximas sessoes",
         "proximos eventos", "tem sessao", "tem evento", "posso visitar",
         "sessoes disponiveis", "agenda", "calendario"],
        "ver_eventos",
        "Vou abrir as sessões disponíveis para você. 🏛",
        "Vou abrir as sessões disponíveis.",
        ["1", "2", "3"],
    ),
    (
        ["minhas confirmacoes", "minhas presencas", "onde confirmei",
         "historico de visitas", "ja confirmei", "confirmacoes"],
        "minhas_confirmacoes",
        "Vou abrir suas confirmações para você ver as próximas e o histórico. ✅",
        "Vou abrir suas confirmações.",
        ["1", "2", "3"],
    ),
    (
        ["meu perfil", "meu cadastro", "meus dados", "ver perfil",
         "ver cadastro", "dados pessoais"],
        "meu_cadastro",
        "Vou abrir seu perfil. Lá você pode consultar e ajustar seus dados. 👤",
        "Vou abrir seu perfil.",
        ["1", "2", "3"],
    ),
    (
        ["meus lembretes", "ativar lembrete", "desativar lembrete",
         "lembrete de sessao", "lembretes"],
        "menu_lembretes",
        "Vou abrir o menu de lembretes para você configurar. 🔔",
        "Vou abrir o menu de lembretes.",
        ["1", "2", "3"],
    ),
    (
        ["ajuda", "central de ajuda", "nao entendi", "como funciona",
         "duvida", "socorro", "me ajuda", "o que eu faco"],
        "menu_ajuda",
        "Vou abrir a Central de Ajuda. Lá tem tutoriais, glossário e perguntas frequentes. 📚",
        "Vou abrir a Central de Ajuda.",
        ["1", "2", "3"],
    ),
    (
        ["glossario", "o que e agape", "o que e vm", "termos",
         "significado de", "o que significa"],
        "ajuda_glossario",
        "Vou abrir o glossário com os termos mais usados. 📖",
        "Vou abrir o glossário.",
        ["1", "2", "3"],
    ),
    (
        ["faq", "perguntas frequentes", "duvidas comuns"],
        "ajuda_faq",
        "Vou abrir as perguntas frequentes do seu nível de acesso.",
        "Vou abrir as perguntas frequentes.",
        ["1", "2", "3"],
    ),
    (
        ["como confirmar presenca", "como confirmo", "confirmar presenca",
         "quero confirmar", "como faco para confirmar"],
        "ver_eventos",
        "Para confirmar presença, abra uma sessão e toque no botão de confirmação. Vou te mostrar as sessões disponíveis. ✅",
        "Vou abrir as sessões para você escolher qual confirmar.",
        ["1", "2", "3"],
    ),
    (
        ["como me cadastrar", "quero me cadastrar", "iniciar cadastro",
         "fazer cadastro", "comecar", "cadastro"],
        "menu_principal",
        "Vou abrir o menu principal. Se ainda não tem cadastro, use o botão de cadastro que aparece no início. 📝",
        "Vou abrir o menu principal.",
        ["1", "2", "3"],
    ),
    # Secretário
    (
        ["area do secretario", "painel do secretario", "menu secretario",
         "area secretario"],
        "area_secretario",
        None,
        "Vou abrir o Painel do Secretário.",
        ["2", "3"],
    ),
    (
        ["meus eventos", "eventos que criei", "gerenciar meus eventos"],
        "meus_eventos",
        None,
        "Vou listar seus eventos para gerenciamento.",
        ["2", "3"],
    ),
    (
        ["minhas lojas", "cadastrar loja", "gerenciar loja"],
        "menu_lojas",
        None,
        "Vou abrir o menu de lojas.",
        ["2", "3"],
    ),
    (
        ["notificacoes", "configurar notificacoes", "ativar notificacoes",
         "desativar notificacoes"],
        "menu_notificacoes",
        None,
        "Vou abrir as configurações de notificações.",
        ["2", "3"],
    ),
]


def _classificar_navegacao(t: str, nivel: str) -> Optional[IAResult]:
    """Tenta classificar como navegação assistida."""
    melhor: Optional[Tuple[str, str, List[str]]] = None
    melhor_score = 0

    for gatilhos, callback, resp1, resp_outros, niveis in _NAV_INTENTS:
        if nivel not in niveis:
            continue
        score = 0
        for g in gatilhos:
            g_norm = _norm(g)
            if g_norm in t:
                score += max(1, len(g_norm.split()))
        if score > melhor_score:
            resposta = resp1 if (nivel == "1" and resp1) else resp_outros
            melhor = (callback, resposta, niveis)
            melhor_score = score

    if not melhor:
        return None

    callback, resposta, _ = melhor
    result = IAResult()
    result.intent = f"nav_{callback}"
    result.confidence = "high"
    result.target_callback = callback
    result.preview_text = resposta
    result.tone = "acolhedor" if nivel == "1" else ("objetivo" if nivel == "2" else "direto")
    return result


# ============================================
# HELPERS PARA INTERAÇÃO MULTI-TURNO
# ============================================

def complementar_evento_com_resposta(
    entities_anterior: Dict[str, str],
    texto_resposta: str,
    nivel: str = "",
    lojas_do_secretario: Optional[List[Dict[str, Any]]] = None,
) -> IAResult:
    """
    Complementa entidades de criação de evento com dados de resposta.

    Usado quando o classificador pediu dados faltantes e o usuário respondeu.
    """
    entities = dict(entities_anterior)

    # Tentar extrair cada campo faltante
    if not entities.get("data"):
        data = _extrair_data(texto_resposta)
        if data:
            entities["data"] = data

    if not entities.get("hora"):
        hora = _extrair_hora(texto_resposta)
        if hora:
            entities["hora"] = hora

    if not entities.get("nome_loja"):
        if nivel == "2":
            _aplicar_loja_em_entities(_obter_loja_padrao_secretario(lojas_do_secretario), entities)
        else:
            loja = _match_loja_no_texto(texto_resposta, lojas_do_secretario)
            _aplicar_loja_em_entities(loja, entities)

    if not entities.get("grau"):
        grau = _extrair_grau(texto_resposta)
        if grau:
            entities["grau"] = grau

    agape_tem, agape_tipo = _extrair_agape(texto_resposta)
    if agape_tem is not None and not entities.get("agape"):
        entities["agape"] = agape_tem
        if agape_tipo:
            entities["agape_tipo"] = agape_tipo

    _extrair_campos_evento_extras(texto_resposta, entities)

    # Verificar se agora está completo
    faltantes = _campos_evento_faltantes(entities)
    result = IAResult()
    result.intent = "criar_evento_natural"
    result.entities = entities
    result.needs_confirmation = True

    if faltantes:
        result.confidence = "medium"
        result.preview_text = _montar_preview_evento_parcial(entities, faltantes)
        result.disambiguation = _perguntar_campos_faltantes(faltantes, nivel)
    else:
        result.confidence = "high"
        result.preview_text = _montar_preview_evento_completo(entities)
        result.target_callback = "ia_confirmar_evento"

    return result


# ============================================
# HELPER DE AUTORIZAÇÃO POR LOJA
# ============================================

def validar_escopo_loja_secretario(
    membro_alvo: Dict[str, Any],
    lojas_do_secretario: List[Dict[str, Any]],
) -> bool:
    """
    Verifica se o membro-alvo pertence a uma loja controlada pelo secretário.

    Usa vínculo por loja_id (se existente) com fallback por nome+número da loja.
    """
    alvo_loja_id = str(membro_alvo.get("ID da loja") or membro_alvo.get("loja_id") or "").strip()
    alvo_loja_nome = _norm(membro_alvo.get("Loja") or membro_alvo.get("loja") or "")
    alvo_loja_numero = str(membro_alvo.get("Número da loja") or membro_alvo.get("numero_loja") or "0").strip()

    for loja in lojas_do_secretario:
        loja_id = str(loja.get("ID") or loja.get("id") or "").strip()
        loja_nome = _norm(loja.get("Nome da Loja") or "")
        loja_numero = str(loja.get("Número") or "0").strip()

        # Match por ID
        if alvo_loja_id and loja_id and alvo_loja_id == loja_id:
            return True

        # Fallback: match por nome + número
        if alvo_loja_nome and loja_nome and alvo_loja_nome == loja_nome:
            if alvo_loja_numero == loja_numero:
                return True

    return False
