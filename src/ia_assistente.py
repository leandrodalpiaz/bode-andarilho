from __future__ import annotations

import ast
import logging
import re
import unicodedata
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Deque, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.bot import navegar_para
from src.permissoes import get_nivel


BASE_IA_PATH = Path(__file__).resolve().parents[1] / "docs" / "ajuda_ia_base.yaml"
logger = logging.getLogger(__name__)
IA_AUDIT_BUFFER_MAX = 5000
IA_AUDIT_BUFFER: Deque[Dict[str, str]] = deque(maxlen=IA_AUDIT_BUFFER_MAX)


@dataclass
class IntentItem:
	intent_id: str
	nivel_permitido: List[str]
	gatilhos: List[str]
	resposta_oficial: str
	acao_tipo: str
	acao_valor: str


def _norm_text(value: str) -> str:
	texto = unicodedata.normalize("NFKD", str(value or ""))
	texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
	texto = texto.lower().strip()
	texto = re.sub(r"\s+", " ", texto)
	return texto


def _parse_list_literal(raw: str) -> List[str]:
	try:
		value = ast.literal_eval(raw.strip())
		if isinstance(value, list):
			return [str(v).strip() for v in value if str(v).strip()]
	except Exception:
		return []
	return []


def _unquote(raw: str) -> str:
	value = raw.strip()
	if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
		return value[1:-1]
	return value


def carregar_intencoes_base() -> List[IntentItem]:
	if not BASE_IA_PATH.exists():
		return []

	linhas = BASE_IA_PATH.read_text(encoding="utf-8").splitlines()
	intencoes: List[IntentItem] = []
	dentro_intencoes = False
	atual: Optional[dict] = None
	dentro_acao = False

	def _finalizar_item() -> None:
		nonlocal atual
		if not atual:
			return
		if not atual.get("intent_id"):
			atual = None
			return
		intencoes.append(
			IntentItem(
				intent_id=str(atual.get("intent_id", "")).strip(),
				nivel_permitido=list(atual.get("nivel_permitido", []) or []),
				gatilhos=list(atual.get("gatilhos", []) or []),
				resposta_oficial=str(atual.get("resposta_oficial", "")).strip(),
				acao_tipo=str(atual.get("acao_tipo", "")).strip(),
				acao_valor=str(atual.get("acao_valor", "")).strip(),
			)
		)
		atual = None

	for linha in linhas:
		raw = linha.rstrip()
		if not raw.strip():
			continue

		if raw.startswith("intencoes:"):
			dentro_intencoes = True
			continue

		if not dentro_intencoes:
			continue

		if re.match(r"^regras_de_roteamento:", raw):
			_finalizar_item()
			break

		if re.match(r"^\s*-\s+intent_id:\s*", raw):
			_finalizar_item()
			intent_id = raw.split("intent_id:", 1)[1].strip()
			atual = {
				"intent_id": _unquote(intent_id),
				"nivel_permitido": [],
				"gatilhos": [],
				"resposta_oficial": "",
				"acao_tipo": "",
				"acao_valor": "",
			}
			dentro_acao = False
			continue

		if not atual:
			continue

		if re.match(r"^\s*acao_recomendada:\s*$", raw):
			dentro_acao = True
			continue

		if dentro_acao and re.match(r"^\s*tipo:\s*", raw):
			atual["acao_tipo"] = _unquote(raw.split("tipo:", 1)[1].strip())
			continue

		if dentro_acao and re.match(r"^\s*valor:\s*", raw):
			atual["acao_valor"] = _unquote(raw.split("valor:", 1)[1].strip())
			continue

		if re.match(r"^\s*nivel_permitido:\s*", raw):
			atual["nivel_permitido"] = _parse_list_literal(raw.split("nivel_permitido:", 1)[1])
			continue

		if re.match(r"^\s*gatilhos:\s*", raw):
			atual["gatilhos"] = _parse_list_literal(raw.split("gatilhos:", 1)[1])
			continue

		if re.match(r"^\s*resposta_oficial:\s*", raw):
			atual["resposta_oficial"] = _unquote(raw.split("resposta_oficial:", 1)[1].strip())
			continue

		if re.match(r"^\s*origem:\s*", raw):
			dentro_acao = False
			continue

	_finalizar_item()
	return intencoes


def _bloqueio_seguranca(texto: str) -> Optional[str]:
	t = _norm_text(texto)

	padroes_dados_pessoais = [
		"dados pessoais", "cpf", "telefone", "email", "endereco", "nascimento", "perfil de outro",
		"dados de outro", "dados do irmao", "vazar", "exportar membros", "lista de membros completa",
	]
	padroes_tecnicos_sensiveis = [
		"supabase key", "token", "senha", "secret", "credentials", "webhook secret",
		"variavel de ambiente", "acesso banco", "query sql", "estrutura interna", "codigo fonte sensivel",
	]
	padroes_admin_sensiveis = [
		"promover sem permissao", "rebaixar sem permissao", "editar membro sem permissao",
		"cancelar evento de outro", "dados admin", "area admin sem acesso",
	]

	if any(p in t for p in padroes_dados_pessoais):
		return (
			"Por seguranca, nao posso expor dados pessoais de terceiros. "
			"Posso te ajudar pelos fluxos oficiais do seu proprio acesso."
		)
	if any(p in t for p in padroes_tecnicos_sensiveis):
		return (
			"Esse tipo de informacao tecnica sensivel nao pode ser exibida aqui. "
			"Posso orientar apenas funcionalidades de uso do bot."
		)
	if any(p in t for p in padroes_admin_sensiveis):
		return (
			"Operacoes administrativas seguem permissao de nivel e fluxo oficial. "
			"Posso te levar para as opcoes permitidas no seu perfil."
		)
	return None


def _classificar_intencao(texto: str, nivel: str, intencoes: List[IntentItem]) -> Optional[IntentItem]:
	t = _norm_text(texto)
	melhor: Optional[IntentItem] = None
	melhor_score = 0

	for item in intencoes:
		if nivel not in item.nivel_permitido:
			continue
		score = 0
		for gatilho in item.gatilhos:
			g = _norm_text(gatilho)
			if g and g in t:
				score += max(1, len(g.split()))
		if score > melhor_score:
			melhor = item
			melhor_score = score

	return melhor


def _mascarar_user_id(user_id: int) -> str:
	raw = str(user_id or "")
	if not raw:
		return "u***"
	return f"u***{raw[-4:]}"


def _auditar_evento(
	evento: str,
	user_id: int,
	nivel: str,
	input_texto: str,
	**extra,
) -> None:
	"""
	Log estruturado de auditoria sem expor conteúdo sensível.

	Regras:
	- Não registra texto bruto da pergunta.
	- Não registra dados pessoais além de um identificador mascarado.
	- Registra apenas metadados operacionais para rastreabilidade.
	"""
	payload = {
		"event": evento,
		"user_ref": _mascarar_user_id(user_id),
		"nivel": str(nivel),
		"input_chars": len(str(input_texto or "")),
		"input_words": len(_norm_text(input_texto).split()) if input_texto else 0,
	}
	payload.update(extra or {})
	logger.info("ia_audit %s", payload)
	IA_AUDIT_BUFFER.append(
		{
			"ts": datetime.now().isoformat(timespec="seconds"),
			"event": str(payload.get("event", "")),
			"nivel": str(payload.get("nivel", "")),
			"user_ref": str(payload.get("user_ref", "")),
			"intent_id": str(payload.get("intent_id", "")),
			"reason": str(payload.get("reason", "")),
			"action_type": str(payload.get("action_type", "")),
		}
	)


def _agregar_metricas(janela_horas: int) -> Dict[str, object]:
	agora = datetime.now()
	corte = agora - timedelta(hours=max(1, int(janela_horas)))

	eventos_janela: List[Dict[str, str]] = []
	for item in IA_AUDIT_BUFFER:
		try:
			ts = datetime.fromisoformat(item.get("ts", ""))
		except Exception:
			continue
		if ts >= corte:
			eventos_janela.append(item)

	total = len(eventos_janela)
	matched = sum(1 for e in eventos_janela if e.get("event") == "intent_matched")
	blocked = sum(1 for e in eventos_janela if e.get("event") == "blocked")
	unmatched = sum(1 for e in eventos_janela if e.get("event") == "unmatched")
	empty = sum(1 for e in eventos_janela if e.get("event") == "empty_input")

	intent_counter = Counter(
		e.get("intent_id", "").strip()
		for e in eventos_janela
		if e.get("event") == "intent_matched" and e.get("intent_id", "").strip()
	)
	reason_counter = Counter(
		e.get("reason", "").strip()
		for e in eventos_janela
		if e.get("event") == "blocked" and e.get("reason", "").strip()
	)

	def _pct(v: int, t: int) -> str:
		if t <= 0:
			return "0.0%"
		return f"{(100.0 * v / t):.1f}%"

	return {
		"janela_horas": janela_horas,
		"total": total,
		"matched": matched,
		"blocked": blocked,
		"unmatched": unmatched,
		"empty_input": empty,
		"taxa_matched": _pct(matched, total),
		"taxa_blocked": _pct(blocked, total),
		"taxa_unmatched": _pct(unmatched, total),
		"top_intents": intent_counter.most_common(5),
		"top_block_reasons": reason_counter.most_common(5),
	}


def _formatar_ranking(items: List[tuple], vazio: str) -> str:
	if not items:
		return vazio
	linhas = []
	for nome, qtd in items:
		linhas.append(f"- {nome}: {qtd}")
	return "\n".join(linhas)


async def assistente_ia_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	user_id = update.effective_user.id if update.effective_user else 0
	nivel = get_nivel(user_id)
	if nivel != "3":
		await navegar_para(
			update,
			context,
			"Observabilidade IA",
			"⛔ Este painel e restrito ao nivel de administrador.",
			InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
		)
		return

	m24 = _agregar_metricas(24)
	m168 = _agregar_metricas(168)
	texto = (
		"*Observabilidade da IA (segura)*\n\n"
		"*Ultimas 24h*\n"
		f"- Total de interacoes: {m24['total']}\n"
		f"- Intencao reconhecida: {m24['matched']} ({m24['taxa_matched']})\n"
		f"- Bloqueios de seguranca: {m24['blocked']} ({m24['taxa_blocked']})\n"
		f"- Nao reconhecidas: {m24['unmatched']} ({m24['taxa_unmatched']})\n"
		f"- Entradas vazias: {m24['empty_input']}\n\n"
		"*Top intencoes (24h)*\n"
		f"{_formatar_ranking(m24['top_intents'], '- Sem dados')}\n\n"
		"*Top motivos de bloqueio (24h)*\n"
		f"{_formatar_ranking(m24['top_block_reasons'], '- Sem bloqueios')}\n\n"
		"*Ultimos 7 dias*\n"
		f"- Total de interacoes: {m168['total']}\n"
		f"- Intencao reconhecida: {m168['matched']} ({m168['taxa_matched']})\n"
		f"- Bloqueios de seguranca: {m168['blocked']} ({m168['taxa_blocked']})\n"
		f"- Nao reconhecidas: {m168['unmatched']} ({m168['taxa_unmatched']})\n\n"
		"_Painel agregado: sem texto bruto e sem dados pessoais de terceiros._"
	)
	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
			[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
		]
	)
	await navegar_para(update, context, "Observabilidade IA", texto, teclado)


def _teclado_acao(item: IntentItem) -> Optional[InlineKeyboardMarkup]:
	if item.acao_tipo != "callback" or not item.acao_valor:
		return None
	return InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("Abrir agora", callback_data=item.acao_valor)],
			[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
			[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
		]
	)


async def assistente_ia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	user_id = update.effective_user.id if update.effective_user else 0
	nivel = get_nivel(user_id)

	texto_entrada = " ".join(context.args or []).strip()
	if not texto_entrada:
		_auditar_evento("empty_input", user_id, nivel, texto_entrada)
		teclado = InlineKeyboardMarkup(
			[
				[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
				[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
			]
		)
		await navegar_para(
			update,
			context,
			"Assistente IA",
			"Use `/ia` seguido da sua duvida. Exemplo: `/ia quais sessoes eu posso visitar essa semana?`",
			teclado,
		)
		return

	mensagem_bloqueio = _bloqueio_seguranca(texto_entrada)
	if mensagem_bloqueio:
		reason = "security_policy_block"
		if "dados pessoais" in mensagem_bloqueio.lower():
			reason = "personal_data_block"
		elif "tecnica sensivel" in mensagem_bloqueio.lower():
			reason = "technical_sensitive_block"
		elif "administrativas" in mensagem_bloqueio.lower():
			reason = "permission_bypass_block"
		_auditar_evento("blocked", user_id, nivel, texto_entrada, reason=reason)
		teclado = InlineKeyboardMarkup(
			[
				[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
				[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
			]
		)
		await navegar_para(update, context, "Assistente IA", mensagem_bloqueio, teclado)
		return

	intencoes = carregar_intencoes_base()
	item = _classificar_intencao(texto_entrada, nivel, intencoes)
	if not item:
		_auditar_evento("unmatched", user_id, nivel, texto_entrada)
		teclado = InlineKeyboardMarkup(
			[
				[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
				[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
			]
		)
		await navegar_para(
			update,
			context,
			"Assistente IA",
			"Nao consegui identificar com seguranca sua intencao. Posso te guiar pela Central de Ajuda ou abrir o menu principal.",
			teclado,
		)
		return

	teclado = _teclado_acao(item)
	_auditar_evento(
		"intent_matched",
		user_id,
		nivel,
		texto_entrada,
		intent_id=item.intent_id,
		action_type=item.acao_tipo,
		action_value=item.acao_valor if item.acao_tipo == "callback" else "informacao",
	)
	await navegar_para(update, context, "Assistente IA", item.resposta_oficial, teclado)
