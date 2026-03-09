from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_GLOSSARIO_INICIAL


GLOSSARIO = {
	"Bot": "Programa de computador que executa tarefas automatizadas no Telegram.",
	"Telegram ID": "Identificador único de cada usuário no Telegram.",
	"Handler": "Função que o bot executa em resposta a uma ação do usuário (ex: clique em botão, envio de mensagem).",
	"Callback Query": "Dados enviados ao bot quando um usuário clica em um botão inline.",
	"Inline Keyboard": "Teclado com botões que aparecem diretamente na mensagem, sem ocupar o teclado do celular.",
	"Webhook": "Mecanismo que permite ao Telegram enviar atualizações para o bot em tempo real.",
	"Scheduler": "Componente que agenda tarefas para serem executadas automaticamente em horários específicos (ex: lembretes).",
	"Google Sheets API": "Interface que permite ao bot ler e escrever dados na planilha Google Sheets.",
	"Conversation Handler": "Tipo de handler que gerencia conversas multi-passo com o usuário, guiando-o por um fluxo de perguntas e respostas.",
	"Ágape": "Refeição fraterna que geralmente ocorre após as sessões maçônicas.",
	"Potência": "Organização maçônica que governa um conjunto de lojas (ex: GOB, GLRGS, CMSB).",
	"Rito": "Conjunto de cerimônias e procedimentos rituais adotados por uma loja ou potência (ex: Rito Escocês Antigo e Aceito, Rito de York).",
	"Oriente": "Termo maçônico que se refere à cidade ou região onde uma loja está localizada.",
	"Grau Mínimo": "O menor grau maçônico que um irmão deve possuir para participar de uma determinada sessão.",
}


async def mostrar_glossario(update, context):
	texto = TEXTO_GLOSSARIO_INICIAL + "\n\n"
	for termo, definicao in GLOSSARIO.items():
		texto += f"*{termo}*: {definicao}\n"

	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar à Central de Ajuda", callback_data="menu_ajuda")]]
	)

	await navegar_para(update, context, "Glossário", texto, teclado)
