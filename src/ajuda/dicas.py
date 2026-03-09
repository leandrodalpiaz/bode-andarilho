from telegram import Update
from telegram.ext import ContextTypes


DICAS_CONTEXTUAIS = {
	"cadastro_evento_data": {
		"texto": "💡 *Dica:* Ao cadastrar a data, use o formato DD/MM/AAAA. Ex: 25/03/2026.",
		"aplicacao": ["cadastro_evento_handler", "DATA"],
	},
	"cadastro_evento_endereco": {
		"texto": "💡 *Dica:* Para que os irmãos possam abrir o local no mapa, cole um link do Google Maps no campo 'Endereço'!",
		"aplicacao": ["cadastro_evento_handler", "ENDERECO"],
	},
	"confirmacao_presenca": {
		"texto": "💡 *Dica:* Lembre-se que você pode cancelar sua presença a qualquer momento se houver imprevistos!",
		"aplicacao": ["eventos.iniciar_confirmacao_presenca"],
	},
	"area_secretario_lojas": {
		"texto": "💡 *Dica:* Cadastre sua loja uma vez para usar os dados como atalho em futuros eventos e agilizar o processo!",
		"aplicacao": ["eventos_secretario.area_secretario_menu"],
	},
}


async def enviar_dica_contextual(
	update: Update,
	context: ContextTypes.DEFAULT_TYPE,
	ponto_gatilho: str,
):
	"""
	Envia uma dica contextual associada ao ponto de gatilho informado.
	"""
	chat_id = update.effective_user.id if update.effective_user else None
	if not chat_id and update.effective_chat:
		chat_id = update.effective_chat.id

	if not chat_id:
		return

	for dica_id, dica_info in DICAS_CONTEXTUAIS.items():
		if ponto_gatilho == dica_id or ponto_gatilho in dica_info["aplicacao"]:
			await context.bot.send_message(
				chat_id=chat_id,
				text=dica_info["texto"],
				parse_mode="Markdown",
			)
			break
