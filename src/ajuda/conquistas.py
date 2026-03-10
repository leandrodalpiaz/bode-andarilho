from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.bot import navegar_para
from src.messages import (
	TEXTO_CONQUISTAS_MEMBRO_INICIAL,
	TEXTO_CONQUISTAS_SECRETARIO_INICIAL,
)
from src.sheets_supabase import buscar_confirmacoes_membro, buscar_eventos_por_secretario


TITULOS_HONORIFICOS = {
	"Andarilho Iniciante": {
		"min_visitas": 1,
		"max_visitas": 1,
		"descricao": "Primeira visita registrada. O primeiro passo de uma longa jornada!",
	},
	"Andarilho Explorador": {
		"min_visitas": 2,
		"max_visitas": 4,
		"descricao": "Visitou algumas lojas. Começando a desbravar novos horizontes.",
	},
	"Andarilho Consagrado": {
		"min_visitas": 5,
		"max_visitas": 9,
		"descricao": "Jornada consolidada, com diversas visitas e novas amizades.",
	},
	"Andarilho Instalado": {
		"min_visitas": 10,
		"max_visitas": 19,
		"descricao": "Um veterano das visitas, com experiência em múltiplos templos.",
	},
	"Andarilho Mestre Viajante": {
		"min_visitas": 20,
		"max_visitas": 49,
		"descricao": "Um verdadeiro mestre na arte da visitação, com vasto conhecimento.",
	},
	"Andarilho Grão-Viajante": {
		"min_visitas": 50,
		"descricao": "O mais alto reconhecimento para quem dedicou-se intensamente à visitação.",
	},
}

MARCOS_SECRETARIO = {
	"Anfitrião Pioneiro": {
		"tipo": "eventos_criados",
		"valor": 1,
		"descricao": "Cadastrou o primeiro evento. Abrindo as portas da fraternidade!",
	},
	"Guia Consagrado": {
		"tipo": "eventos_criados",
		"valor": 5,
		"descricao": "Organizou 5 eventos. Sua orientação já é reconhecida.",
	},
	"Condutor Soberano": {
		"tipo": "eventos_criados",
		"valor": 10,
		"descricao": "Conduziu 10 eventos. Um verdadeiro pilar na organização.",
	},
	"Instrutor de Aprendizes": {
		"tipo": "primeiro_grau",
		"grau": "Aprendiz",
		"descricao": "Cadastrou o primeiro evento com grau mínimo Aprendiz.",
	},
	"Instrutor de Companheiros": {
		"tipo": "primeiro_grau",
		"grau": "Companheiro",
		"descricao": "Cadastrou o primeiro evento com grau mínimo Companheiro.",
	},
	"Instrutor de Mestres": {
		"tipo": "primeiro_grau",
		"grau": "Mestre",
		"descricao": "Cadastrou o primeiro evento com grau mínimo Mestre.",
	},
	"Guardião de Ritos": {
		"tipo": "diversidade_ritos",
		"valor": 3,
		"descricao": "Cadastrou eventos de 3 ritos diferentes. Zelo pela qualidade dos ritos.",
	},
	"Embaixador de Orientes": {
		"tipo": "diversidade_orientes",
		"valor": 3,
		"descricao": "Cadastrou eventos para 3 cidades/orientes diferentes. Conectando diferentes locais.",
	},
	"Escriba Incansável": {
		"tipo": "meses_consecutivos",
		"valor": 3,
		"descricao": "Cadastrou pelo menos 1 evento em 3 meses consecutivos. Disciplina e constância.",
	},
}


def _adicionar_marco_unico(marcos_atuais: list, nome_marco: str):
	descricao = MARCOS_SECRETARIO[nome_marco]["descricao"]
	linha = f"✨ *{nome_marco}*: {descricao}"
	if linha not in marcos_atuais:
		marcos_atuais.append(linha)


def _parse_data_evento(texto: str):
	if not texto:
		return None
	texto = str(texto).strip()
	formatos = ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S")
	for fmt in formatos:
		try:
			return datetime.strptime(texto, fmt)
		except ValueError:
			continue
	return None


async def calcular_conquistas_membro(user_id: int) -> list:
	confirmacoes = await buscar_confirmacoes_membro(user_id)
	num_visitas = len(confirmacoes)

	conquistas_atuais = []
	for titulo, dados in TITULOS_HONORIFICOS.items():
		min_visitas = dados["min_visitas"]
		max_visitas = dados.get("max_visitas")

		if num_visitas >= min_visitas and (max_visitas is None or num_visitas <= max_visitas):
			conquistas_atuais.append(f"✨ *{titulo}*: {dados['descricao']}")

	return conquistas_atuais


async def mostrar_conquistas_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	conquistas = await calcular_conquistas_membro(user_id)

	texto = TEXTO_CONQUISTAS_MEMBRO_INICIAL + "\n\n"
	if conquistas:
		texto += "\n".join(conquistas)
	else:
		texto += "Você ainda não possui títulos honoríficos. Comece a visitar sessões para ganhar o seu primeiro!"

	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao menu principal", callback_data="menu_principal")]]
	)

	await navegar_para(update, context, "Minhas Conquistas", texto, teclado)


async def calcular_marcos_secretario(user_id: int) -> list:
	eventos = await buscar_eventos_por_secretario(user_id)
	marcos_atuais = []

	eventos_criados = len(eventos)
	for marco, dados in MARCOS_SECRETARIO.items():
		if dados["tipo"] == "eventos_criados" and eventos_criados >= dados["valor"]:
			_adicionar_marco_unico(marcos_atuais, marco)

	ritos_diferentes = {e.get("Rito") for e in eventos if e.get("Rito")}
	if len(ritos_diferentes) >= MARCOS_SECRETARIO["Guardião de Ritos"]["valor"]:
		_adicionar_marco_unico(marcos_atuais, "Guardião de Ritos")

	orientes_diferentes = {e.get("Oriente") for e in eventos if e.get("Oriente")}
	if len(orientes_diferentes) >= MARCOS_SECRETARIO["Embaixador de Orientes"]["valor"]:
		_adicionar_marco_unico(marcos_atuais, "Embaixador de Orientes")

	graus_registrados = {str(e.get("Grau", "")).strip() for e in eventos if e.get("Grau")}
	if "Aprendiz" in graus_registrados:
		_adicionar_marco_unico(marcos_atuais, "Instrutor de Aprendizes")
	if "Companheiro" in graus_registrados:
		_adicionar_marco_unico(marcos_atuais, "Instrutor de Companheiros")
	if "Mestre" in graus_registrados:
		_adicionar_marco_unico(marcos_atuais, "Instrutor de Mestres")

	alvo_meses = MARCOS_SECRETARIO["Escriba Incansável"]["valor"]
	meses_com_eventos = set()
	for evento in eventos:
		dt = _parse_data_evento(evento.get("Data do evento", ""))
		if dt:
			meses_com_eventos.add((dt.year, dt.month))

	meses_ordenados = sorted(meses_com_eventos)
	if len(meses_ordenados) >= alvo_meses:
		sequencia = 1
		for i in range(1, len(meses_ordenados)):
			ano_ant, mes_ant = meses_ordenados[i - 1]
			ano_atual, mes_atual = meses_ordenados[i]

			eh_mes_seguinte = (
				(ano_atual == ano_ant and mes_atual == mes_ant + 1)
				or (ano_atual == ano_ant + 1 and mes_ant == 12 and mes_atual == 1)
			)

			if eh_mes_seguinte:
				sequencia += 1
				if sequencia >= alvo_meses:
					_adicionar_marco_unico(marcos_atuais, "Escriba Incansável")
					break
			else:
				sequencia = 1

	return marcos_atuais


async def mostrar_marcos_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	marcos = await calcular_marcos_secretario(user_id)

	texto = TEXTO_CONQUISTAS_SECRETARIO_INICIAL + "\n\n"
	if marcos:
		texto += "\n".join(marcos)
	else:
		texto += "Você ainda não atingiu nenhum marco de reconhecimento. Comece a cadastrar eventos para ser reconhecido!"

	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar à Área do Secretário", callback_data="area_secretario")]]
	)

	await navegar_para(update, context, "Meus Marcos de Secretário", texto, teclado)
