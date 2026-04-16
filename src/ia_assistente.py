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
from src.ia_multinivel import (
	IAResult,
	classificar_intencao_multinivel,
	complementar_evento_com_resposta,
	validar_escopo_loja_secretario,
	CAMPOS_EDITAVEIS_IA,
)


BASE_IA_PATH = Path(__file__).resolve().parents[1] / "docs" / "ajuda_ia_base.yaml"
logger = logging.getLogger(__name__)
IA_AUDIT_BUFFER_MAX = 5000
IA_AUDIT_BUFFER: Deque[Dict[str, str]] = deque(maxlen=IA_AUDIT_BUFFER_MAX)
STOPWORDS_PT = {
	"a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos", "e", "em", "eu",
	"me", "meu", "minha", "minhas", "meus", "na", "nas", "no", "nos", "o", "os", "ou",
	"para", "por", "pra", "que", "se", "sem", "tem", "tenho", "uma", "um", "ver", "quero",
	"qual", "quais", "onde", "porque", "por que", "posso", "preciso", "abrir", "bot", "ia",
}
TERMOS_SENSIVEIS_FILTRO = {
	"admin", "banco", "chave", "credenciais", "cpf", "dados", "email", "endereco", "nascimento",
	"secret", "senha", "supabase", "telefone", "token", "webhook",
}


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


def _extrair_topic_hint(texto: str) -> str:
	"""
	Resume o tema em poucos tokens seguros para analise agregada.

	- Remove stopwords.
	- Remove termos claramente sensiveis.
	- Nao preserva frase completa.
	"""
	tokens = re.findall(r"[a-z0-9_]+", _norm_text(texto))
	seguros: List[str] = []
	for token in tokens:
		if len(token) < 3:
			continue
		if token in STOPWORDS_PT:
			continue
		if token in TERMOS_SENSIVEIS_FILTRO:
			continue
		if token.isdigit():
			continue
		seguros.append(token)

	unicos: List[str] = []
	for token in seguros:
		if token not in unicos:
			unicos.append(token)
		if len(unicos) >= 4:
			break
	return " ".join(unicos)


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
			"topic_hint": str(payload.get("topic_hint", "")),
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


def _formatar_linhas(items: List[str], vazio: str) -> str:
	if not items:
		return vazio
	return "\n".join(f"- {item}" for item in items)


def _eventos_na_janela(janela_horas: int) -> List[Dict[str, str]]:
	agora = datetime.now()
	corte = agora - timedelta(hours=max(1, int(janela_horas)))
	eventos: List[Dict[str, str]] = []
	for item in IA_AUDIT_BUFFER:
		try:
			ts = datetime.fromisoformat(item.get("ts", ""))
		except Exception:
			continue
		if ts >= corte:
			eventos.append(item)
	return eventos


def _sugestoes_aprendizado(janela_horas: int = 168) -> Dict[str, object]:
	eventos = _eventos_na_janela(janela_horas)
	unmatched_topics = Counter(
		e.get("topic_hint", "").strip()
		for e in eventos
		if e.get("event") == "unmatched" and e.get("topic_hint", "").strip()
	)
	matched_intents = Counter(
		e.get("intent_id", "").strip()
		for e in eventos
		if e.get("event") == "intent_matched" and e.get("intent_id", "").strip()
	)
	block_reasons = Counter(
		e.get("reason", "").strip()
		for e in eventos
		if e.get("event") == "blocked" and e.get("reason", "").strip()
	)

	sugestoes: List[str] = []
	for topic, qtd in unmatched_topics.most_common(5):
		if qtd < 2:
			continue
		sugestoes.append(
			f"Criar ou ampliar intencao para tema recorrente: `{topic}` ({qtd} ocorrencias nao reconhecidas)."
		)
		sugestoes.append(
			f"Avaliar FAQ/tutorial curto para `{topic}` e adicionar novos gatilhos no YAML."
		)

	for intent_id, qtd in matched_intents.most_common(5):
		if qtd < 3:
			continue
		sugestoes.append(
			f"Revisar UX da intencao `{intent_id}`: alta procura ({qtd} usos) sugere destaque maior no menu ou ajuda."
		)

	for reason, qtd in block_reasons.most_common(3):
		if qtd < 2:
			continue
		sugestoes.append(
			f"Bloqueio recorrente `{reason}` ({qtd} ocorrencias): reforcar texto explicativo ou tutorial de limites do assistente."
		)

	if not sugestoes:
		sugestoes.append("Ainda ha pouco volume para sugestoes fortes. Continue coletando interacoes reais do piloto.")

	return {
		"janela_horas": janela_horas,
		"top_unmatched_topics": unmatched_topics.most_common(5),
		"top_matched_intents": matched_intents.most_common(5),
		"top_block_reasons": block_reasons.most_common(5),
		"sugestoes": sugestoes[:10],
	}


def _plano_semanal_aprendizado(janela_horas: int = 168) -> Dict[str, List[str]]:
	dados = _sugestoes_aprendizado(janela_horas)
	alta: List[str] = []
	media: List[str] = []
	monitorar: List[str] = []

	for topic, qtd in dados["top_unmatched_topics"]:
		if not topic:
			continue
		if qtd >= 4:
			alta.append(
				f"Criar ou ampliar intencao para `{topic}` e adicionar FAQ/tutorial curto ({qtd} nao reconhecidas)."
			)
		elif qtd >= 2:
			media.append(
				f"Revisar gatilhos e ajuda para `{topic}` ({qtd} nao reconhecidas)."
			)
		else:
			monitorar.append(
				f"Continuar observando tema `{topic}` antes de alterar o bot."
			)

	for intent_id, qtd in dados["top_matched_intents"]:
		if not intent_id:
			continue
		if qtd >= 6:
			media.append(
				f"Dar mais destaque no menu/ajuda para `{intent_id}` ({qtd} usos reconhecidos)."
			)
		elif qtd >= 3:
			monitorar.append(
				f"Confirmar se a UX atual de `{intent_id}` esta clara para o usuario."
			)

	for reason, qtd in dados["top_block_reasons"]:
		if not reason:
			continue
		if qtd >= 3:
			alta.append(
				f"Reforcar mensagem explicativa para bloqueio `{reason}` ({qtd} ocorrencias)."
			)
		elif qtd >= 2:
			media.append(
				f"Adicionar orientacao curta sobre limite de seguranca `{reason}`."
			)

	if not alta and not media and not monitorar:
		monitorar.append("Pouco volume nesta semana. Continue coletando interacoes do piloto.")

	return {
		"alta": alta[:3],
		"media": media[:4],
		"monitorar": monitorar[:4],
	}


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


async def assistente_ia_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	user_id = update.effective_user.id if update.effective_user else 0
	nivel = get_nivel(user_id)
	if nivel != "3":
		await navegar_para(
			update,
			context,
			"Aprendizado IA",
			"⛔ Este relatorio e restrito ao nivel de administrador.",
			InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
		)
		return

	dados = _sugestoes_aprendizado(168)
	plano = _plano_semanal_aprendizado(168)
	texto = (
		"*Relatorio Semanal de Aprendizado da IA*\n\n"
		"*Acoes recomendadas para esta semana*\n"
		"*Alta prioridade*\n"
		f"{_formatar_linhas(plano['alta'], '- Nenhuma acao critica agora')}\n\n"
		"*Media prioridade*\n"
		f"{_formatar_linhas(plano['media'], '- Nenhuma acao media agora')}\n\n"
		"*Monitorar*\n"
		f"{_formatar_linhas(plano['monitorar'], '- Sem pontos de monitoramento')}\n\n"
		"*Base de evidencias (7d)*\n"
		"*Temas nao reconhecidos mais recorrentes (7d)*\n"
		f"{_formatar_ranking(dados['top_unmatched_topics'], '- Sem dados suficientes')}\n\n"
		"*Intencoes mais usadas (7d)*\n"
		f"{_formatar_ranking(dados['top_matched_intents'], '- Sem dados suficientes')}\n\n"
		"*Motivos de bloqueio mais frequentes (7d)*\n"
		f"{_formatar_ranking(dados['top_block_reasons'], '- Sem bloqueios relevantes')}\n\n"
		"*Sugestoes brutas da analise*\n"
		f"{_formatar_linhas(dados['sugestoes'], '- Sem sugestoes')}\n\n"
		"_Aprovacao humana continua obrigatoria antes de alterar ajuda, YAML ou codigo._"
	)
	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
			[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
		]
	)
	await navegar_para(update, context, "Aprendizado IA", texto, teclado)


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


async def _executar_assistente_ia(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_entrada: str) -> None:
	user_id = update.effective_user.id if update.effective_user else 0
	nivel = get_nivel(user_id)

	if not texto_entrada:
		_auditar_evento("empty_input", user_id, nivel, texto_entrada, topic_hint="")
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
			"Escreva sua duvida normalmente aqui no privado. Exemplo: quais sessoes eu posso visitar essa semana?",
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
		_auditar_evento("blocked", user_id, nivel, texto_entrada, reason=reason, topic_hint="")
		teclado = InlineKeyboardMarkup(
			[
				[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
				[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
			]
		)
		await navegar_para(update, context, "Assistente IA", mensagem_bloqueio, teclado)
		return

	# ── 1) Verificar se é continuação de criação de evento multi-turno ──
	pending = context.user_data.get("ia_evento_pendente")
	if pending and isinstance(pending, dict):
		await _tratar_complemento_evento(update, context, texto_entrada, user_id, nivel, pending)
		return

	# ── 2) Classificador multinível (antes do YAML base) ──────────────
	lojas_sec = _obter_lojas_do_ator(user_id, nivel)
	ia_result = classificar_intencao_multinivel(texto_entrada, nivel, lojas_sec)

	if ia_result.intent and ia_result.confidence in ("high", "medium"):
		await _despachar_ia_result(update, context, texto_entrada, user_id, nivel, ia_result)
		return

	# ── 3) Fallback YAML base (classificador original) ────────────────
	intencoes = carregar_intencoes_base()
	item = _classificar_intencao(texto_entrada, nivel, intencoes)
	if item:
		teclado = _teclado_acao(item)
		_auditar_evento(
			"intent_matched",
			user_id,
			nivel,
			texto_entrada,
			intent_id=item.intent_id,
			action_type=item.acao_tipo,
			action_value=item.acao_valor if item.acao_tipo == "callback" else "informacao",
			topic_hint=_extrair_topic_hint(texto_entrada),
		)
		await navegar_para(update, context, "Assistente IA", item.resposta_oficial, teclado)
		return

	# ── 4) Sem match → fallback original ──────────────────────────────
	_auditar_evento("unmatched", user_id, nivel, texto_entrada, topic_hint=_extrair_topic_hint(texto_entrada))
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


def _obter_lojas_do_ator(user_id: int, nivel: str) -> Optional[List[Dict[str, str]]]:
	"""Carrega lojas do ator para alimentar classificador, somente se relevante."""
	if nivel not in ("2", "3"):
		return None
	try:
		from src.sheets_supabase import listar_lojas_visiveis
		return listar_lojas_visiveis(user_id, nivel) or []
	except Exception as e:
		logger.warning("Falha ao carregar lojas para IA multinivel: %s", e)
		return []


async def _despachar_ia_result(
	update: Update,
	context: ContextTypes.DEFAULT_TYPE,
	texto_entrada: str,
	user_id: int,
	nivel: str,
	result: IAResult,
) -> None:
	"""Despacha o resultado do classificador multinível."""
	# Bloqueio
	if result.blocked:
		_auditar_evento(
			"blocked", user_id, nivel, texto_entrada,
			reason=result.block_reason,
			intent_id=result.intent,
			topic_hint=_extrair_topic_hint(texto_entrada),
		)
		teclado = InlineKeyboardMarkup(
			[[InlineKeyboardButton("Menu principal", callback_data=result.target_callback or "menu_principal")]]
		)
		await navegar_para(update, context, "Assistente IA", result.preview_text, teclado)
		return

	# Criação de evento com dados faltantes → iniciar multi-turno
	if result.intent == "criar_evento_natural" and result.disambiguation:
		context.user_data["ia_evento_pendente"] = result.entities
		_auditar_evento(
			"intent_matched", user_id, nivel, texto_entrada,
			intent_id="criar_evento_natural",
			action_type="multi_turno",
			topic_hint=_extrair_topic_hint(texto_entrada),
		)
		texto_resposta = result.preview_text + "\n\n" + result.disambiguation
		teclado = InlineKeyboardMarkup(
			[[InlineKeyboardButton("❌ Cancelar", callback_data="ia_cancelar_evento")]]
		)
		await navegar_para(update, context, "Assistente IA > Criar Evento", texto_resposta, teclado)
		return

	# Criação de evento completa → preview + confirmação
	if result.intent == "criar_evento_natural" and result.target_callback == "ia_confirmar_evento":
		context.user_data["ia_evento_pendente"] = result.entities
		_auditar_evento(
			"intent_matched", user_id, nivel, texto_entrada,
			intent_id="criar_evento_natural",
			action_type="preview_confirm",
			topic_hint=_extrair_topic_hint(texto_entrada),
		)
		teclado = InlineKeyboardMarkup([
			[InlineKeyboardButton("✅ Confirmar e publicar", callback_data="ia_confirmar_evento")],
			[InlineKeyboardButton("✏️ Editar dados", callback_data="ia_editar_evento")],
			[InlineKeyboardButton("❌ Cancelar", callback_data="ia_cancelar_evento")],
		])
		await navegar_para(update, context, "Assistente IA > Criar Evento", result.preview_text, teclado)
		return

	# Navegação / callback direto
	if result.target_callback:
		_auditar_evento(
			"intent_matched", user_id, nivel, texto_entrada,
			intent_id=result.intent,
			action_type="callback",
			action_value=result.target_callback,
			topic_hint=_extrair_topic_hint(texto_entrada),
		)
		teclado = InlineKeyboardMarkup([
			[InlineKeyboardButton("Abrir agora", callback_data=result.target_callback)],
			[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
			[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
		])
		await navegar_para(update, context, "Assistente IA", result.preview_text, teclado)
		return


async def _tratar_complemento_evento(
	update: Update,
	context: ContextTypes.DEFAULT_TYPE,
	texto: str,
	user_id: int,
	nivel: str,
	entities_anterior: Dict[str, str],
) -> None:
	"""Trata a resposta de continuação da criação de evento."""
	lojas_sec = _obter_lojas_do_ator(user_id, nivel)
	result = complementar_evento_com_resposta(entities_anterior, texto, lojas_sec)

	if result.disambiguation:
		# Ainda faltam dados
		context.user_data["ia_evento_pendente"] = result.entities
		texto_resp = result.preview_text + "\n\n" + result.disambiguation
		teclado = InlineKeyboardMarkup(
			[[InlineKeyboardButton("❌ Cancelar", callback_data="ia_cancelar_evento")]]
		)
		await navegar_para(update, context, "Assistente IA > Criar Evento", texto_resp, teclado)
		return

	# Completo → preview + confirmar
	context.user_data["ia_evento_pendente"] = result.entities
	_auditar_evento(
		"intent_matched", user_id, nivel, texto,
		intent_id="criar_evento_natural",
		action_type="preview_confirm",
		topic_hint=_extrair_topic_hint(texto),
	)
	teclado = InlineKeyboardMarkup([
		[InlineKeyboardButton("✅ Confirmar e publicar", callback_data="ia_confirmar_evento")],
		[InlineKeyboardButton("✏️ Editar dados", callback_data="ia_editar_evento")],
		[InlineKeyboardButton("❌ Cancelar", callback_data="ia_cancelar_evento")],
	])
	await navegar_para(update, context, "Assistente IA > Criar Evento", result.preview_text, teclado)


def _eh_pedido_stats_sem_comando(texto: str) -> bool:
	t = _norm_text(texto)
	return any(
		chave in t
		for chave in (
			"ia stats",
			"assistente stats",
			"metricas ia",
			"metricas do assistente",
			"observabilidade ia",
		)
	)


def _eh_pedido_relatorio_sem_comando(texto: str) -> bool:
	t = _norm_text(texto)
	return any(
		chave in t
		for chave in (
			"ia relatorio",
			"assistente relatorio",
			"relatorio ia",
			"relatorio do assistente",
			"aprendizado ia",
		)
	)


def _eh_chamada_menu_privado(texto: str) -> bool:
	t = _norm_text(texto)
	return t in {
		"menu",
		"painel",
		"bode",
		"menu principal",
		"abrir menu",
		"voltar menu",
	}


async def abrir_assistente_ia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	nivel = get_nivel(update.effective_user.id if update.effective_user else 0)
	linhas = [
		[InlineKeyboardButton("Ver sessoes", callback_data="ver_eventos")],
		[InlineKeyboardButton("Minhas confirmacoes", callback_data="minhas_confirmacoes")],
		[InlineKeyboardButton("Meu perfil", callback_data="meu_cadastro")],
		[InlineKeyboardButton("Central de Ajuda", callback_data="menu_ajuda")],
		[InlineKeyboardButton("Voltar ao menu", callback_data="menu_principal")],
	]
	if nivel == "3":
		linhas.insert(3, [InlineKeyboardButton("Metricas IA", callback_data="abrir_assistente_stats")])
		linhas.insert(4, [InlineKeyboardButton("Relatorio IA", callback_data="abrir_assistente_relatorio")])

	teclado = InlineKeyboardMarkup(linhas)
	await navegar_para(
		update,
		context,
		"Assistente IA",
		"Escreva sua duvida em linguagem natural aqui no privado. Tambem pode usar os atalhos abaixo.",
		teclado,
	)


async def assistente_ia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	texto_entrada = " ".join(context.args or []).strip()
	await _executar_assistente_ia(update, context, texto_entrada)


async def assistente_ia_texto_livre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	if not update.message:
		return
	if update.effective_chat and update.effective_chat.type != "private":
		return

	texto = (update.message.text or "").strip()
	if not texto:
		return

	if _eh_chamada_menu_privado(texto):
		# Reusa o fluxo oficial de /start para reconstruir o painel no privado.
		from src.bot import start
		await start(update, context)
		return

	if _eh_pedido_stats_sem_comando(texto):
		await assistente_ia_stats(update, context)
		return
	if _eh_pedido_relatorio_sem_comando(texto):
		await assistente_ia_relatorio(update, context)
		return

	await _executar_assistente_ia(update, context, texto)


# ============================================
# CALLBACKS DE CRIAÇÃO DE EVENTO POR LINGUAGEM NATURAL
# ============================================

async def ia_confirmar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	"""Confirma e publica o evento criado por linguagem natural, delegando ao fluxo existente."""
	query = update.callback_query
	if query:
		await query.answer()

	user_id = update.effective_user.id
	nivel = get_nivel(user_id)
	entities = context.user_data.pop("ia_evento_pendente", None)

	if not entities or not isinstance(entities, dict):
		await navegar_para(
			update, context, "Assistente IA",
			"Nenhum rascunho de evento encontrado. Tente novamente.",
			InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
		)
		return

	if nivel not in ("2", "3"):
		await navegar_para(
			update, context, "Assistente IA",
			"⛔ Apenas secretários e administradores podem cadastrar eventos.",
			InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
		)
		return

	# Popula context.user_data com os campos do evento no formato esperado pelo fluxo oficial
	_popular_contexto_evento(context, entities, user_id, update.effective_user.full_name or "")

	# Reutiliza o builder e publicador oficiais do cadastro de evento
	try:
		from src.cadastro_evento import _montar_evento_dict, _publicar_e_finalizar, listar_eventos, _encontrar_duplicado

		evento = _montar_evento_dict(context)
		eventos_existentes = listar_eventos() or []
		dup = _encontrar_duplicado(evento, eventos_existentes)

		if dup:
			from src.cadastro_evento import _montar_resumo_evento_md
			texto = _montar_resumo_evento_md(evento, duplicado=dup)
			texto += "\n\n⚠️ Evento duplicado detectado! Deseja publicar mesmo assim?"
			teclado = InlineKeyboardMarkup([
				[InlineKeyboardButton("⚠️ Publicar mesmo assim", callback_data="ia_forcar_evento")],
				[InlineKeyboardButton("❌ Cancelar", callback_data="ia_cancelar_evento")],
			])
			context.user_data["ia_evento_pendente"] = entities
			await navegar_para(update, context, "Assistente IA > Criar Evento", texto, teclado)
			return

		await _publicar_e_finalizar(update, context, evento)
		from src.cadastro_evento import _limpar_contexto_evento
		_limpar_contexto_evento(context)
	except Exception as e:
		logger.error("Erro ao publicar evento por IA: %s", e)
		await navegar_para(
			update, context, "Assistente IA",
			f"❌ Erro ao publicar evento: {e}",
			InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
		)


async def ia_forcar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	"""Publica evento mesmo com duplicidade."""
	query = update.callback_query
	if query:
		await query.answer()

	user_id = update.effective_user.id
	entities = context.user_data.pop("ia_evento_pendente", None)

	if not entities:
		await navegar_para(
			update, context, "Assistente IA",
			"Nenhum rascunho de evento encontrado.",
			InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
		)
		return

	_popular_contexto_evento(context, entities, user_id, update.effective_user.full_name or "")

	try:
		from src.cadastro_evento import _montar_evento_dict, _publicar_e_finalizar, _limpar_contexto_evento
		evento = _montar_evento_dict(context)
		await _publicar_e_finalizar(update, context, evento, forcar=True)
		_limpar_contexto_evento(context)
	except Exception as e:
		logger.error("Erro ao forçar publicação de evento por IA: %s", e)
		await navegar_para(
			update, context, "Assistente IA",
			f"❌ Erro ao publicar evento: {e}",
			InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
		)


async def ia_editar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	"""Abre o fluxo oficial de cadastro de evento para edição manual."""
	query = update.callback_query
	if query:
		await query.answer()

	# Mantém o rascunho mas redireciona para o fluxo conversacional oficial
	context.user_data.pop("ia_evento_pendente", None)
	from src.bot import navegar_para as _nav
	await _nav(
		update, context, "Assistente IA",
		"Vou abrir o fluxo de cadastro manual para você ajustar os dados.",
		InlineKeyboardMarkup([
			[InlineKeyboardButton("📝 Abrir cadastro manual", callback_data="cadastrar_evento")],
			[InlineKeyboardButton("Menu principal", callback_data="menu_principal")],
		]),
	)


async def ia_cancelar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	"""Cancela a criação de evento por linguagem natural."""
	query = update.callback_query
	if query:
		await query.answer()

	context.user_data.pop("ia_evento_pendente", None)
	await navegar_para(
		update, context, "Assistente IA",
		"Criação de evento cancelada.",
		InlineKeyboardMarkup([[InlineKeyboardButton("Menu principal", callback_data="menu_principal")]]),
	)


def _popular_contexto_evento(
	context: ContextTypes.DEFAULT_TYPE,
	entities: Dict[str, str],
	user_id: int,
	user_name: str,
) -> None:
	"""Popula context.user_data com dados extraídos para reutilizar _montar_evento_dict."""
	import os
	GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID", "-1003721338228")

	context.user_data["novo_evento_data"] = entities.get("data", "")
	context.user_data["novo_evento_horario"] = entities.get("hora", "")
	context.user_data["novo_evento_nome_loja"] = entities.get("nome_loja", "")
	context.user_data["novo_evento_numero_loja"] = entities.get("numero_loja", "")
	context.user_data["novo_evento_oriente"] = entities.get("oriente", "")
	context.user_data["novo_evento_grau"] = entities.get("grau", "Aprendiz")
	context.user_data["novo_evento_tipo_sessao"] = entities.get("tipo_sessao", "")
	context.user_data["novo_evento_rito"] = entities.get("rito", "")
	context.user_data["novo_evento_potencia"] = entities.get("potencia", "")
	context.user_data["novo_evento_traje"] = entities.get("traje", "")
	context.user_data["novo_evento_endereco"] = entities.get("endereco", "")
	context.user_data["novo_evento_loja_id"] = entities.get("loja_id", "")

	# Ágape
	agape = entities.get("agape", "nao")
	context.user_data["novo_evento_agape"] = agape
	context.user_data["novo_evento_agape_tipo"] = entities.get("agape_tipo", "")

	# Observações
	obs = entities.get("observacoes", "")
	context.user_data["novo_evento_observacoes_tem"] = "sim" if obs else "nao"
	context.user_data["novo_evento_observacoes_texto"] = obs

	# Auditoria
	context.user_data["novo_evento_secretario_responsavel_id"] = str(user_id)
	context.user_data["novo_evento_telegram_id_secretario"] = str(user_id)
	context.user_data["novo_evento_secretario_responsavel_nome"] = user_name
	context.user_data["novo_evento_criado_por_id"] = str(user_id)
	context.user_data["novo_evento_criado_por_nome"] = user_name
	context.user_data["novo_evento_telegram_id_grupo"] = GRUPO_PRINCIPAL_ID
