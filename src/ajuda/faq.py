from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_FAQ_INICIAL
from src.permissoes import get_nivel


FAQ_NIVEL1 = [
	(
		"*Como começo a usar o bot?*",
		"Digite */bode* no grupo da sua loja ou */start* no privado do bot. Faça o cadastro rápido e pronto!",
	),
	(
		"*Já sou cadastrado, mas o bot está pedindo cadastro de novo. O que houve?*",
		"Isso pode acontecer se você interagiu com o bot no grupo e ele te redirecionou para o privado, mas você ainda não tinha iniciado conversa lá. Basta digitar */start* no privado que o bot vai reconhecer seu cadastro e mostrar o menu.",
	),
	(
		"*Esqueci de confirmar com ágape, como corrijo?*",
		"Simples: cancele sua presença atual e confirme novamente escolhendo a opção desejada.",
	),
	(
		"*Quis mudar de 'com ágape' para 'sem ágape' (ou vice-versa)*",
		"Mesmo procedimento: cancele e confirme novamente com a opção correta.",
	),
	(
		"*O que significa 'VM' antes de alguns nomes na lista?*",
		"'VM' significa *Venerável Mestre*. Durante o cadastro, o irmão informa se é Venerável Mestre. Quem responde 'Sim' aparece com 'VM' antes do nome na lista de confirmados. É uma informação importante para o protocolo de recepção nas lojas.",
	),
	(
		"*Apaguei a conversa com o bot, perdi tudo?*",
		"*Não se preocupe!* O bot guarda todas as informações na planilha. Basta digitar */bode* no grupo ou */start* no privado que ele recria o menu automaticamente.",
	),
	(
		"*O bot não responde no grupo. O que faço?*",
		"Pode ser que: o bot esteja 'inicializando' (espere alguns segundos e tente novamente); você digitou algo diferente de 'bode' (só funciona a palavra isolada); tente enviar */start no privado* para ver se o bot está vivo. Se mesmo assim não funcionar, aguarde alguns minutos e tente novamente.",
	),
	(
		"*Posso ver eventos passados que participei?*",
		"Sim! Vá em *'✅ Minhas confirmações'* e depois em *'📜 Histórico'*. Lá estão todos os eventos que você já participou.",
	),
	(
		"*Como faço para o endereço abrir no mapa?*",
		"Se o secretário colocou um *link do Google Maps* no endereço, vai aparecer um botão *'📍 Abrir no mapa'* nos detalhes do evento. Basta clicar que abre no GPS do celular!",
	),
	(
		"*Recebi uma mensagem 'MEIO DIA EM PONTO!' O que significa?*",
		"É o lembrete do dia do evento! O bot envia essa mensagem ao meio-dia para lembrar que hoje tem sessão. É uma tradição do nosso meio.",
	),
	(
		"*O bot disse 'Função em desenvolvimento'. É erro?*",
		"Não é erro! Significa que aquela funcionalidade ainda está sendo implementada. Se achar que já deveria funcionar, avise o secretário da sua loja.",
	),
	(
		"*Ainda tenho dúvidas. Com quem falo?*",
		"Para questões sobre o bot, procure o *secretário da sua loja*. Ele é o responsável por ajudar os membros e pode resolver a maioria das questões.",
	),
]

FAQ_NIVEL2 = [
	(
		"*Posso criar sessão falando de forma natural?*",
		"Sim. Você pode descrever a sessão em linguagem natural no Assistente IA, por exemplo informando grau, data, horário e ágape na mesma frase. Se faltar algum dado, o bot pergunta apenas o que falta antes da confirmação.",
	),
	(
		"*Como a loja funciona quando eu crio uma sessão pela IA?*",
		"Para secretário, a loja vinculada ao perfil é usada automaticamente na IA. Para administrador, se a frase não trouxer a loja, o bot pedirá explicitamente a loja do evento antes de continuar.",
	),
	(
		"*Esqueci de incluir o ágape ao cadastrar um evento, como corrigir?*",
		"Você pode *editar o evento* e corrigir a informação. Mas lembre-se: ao editar, todas as confirmações atuais serão removidas. Os irmãos precisarão confirmar novamente.",
	),
	(
		"*Um irmão disse que confirmou, mas não aparece na lista de confirmados do meu evento*",
		"Verifique: se o evento ainda não passou; se o irmão realmente clicou em 'Confirmar' (ele recebe uma mensagem de confirmação no privado); se necessário, peça para ele confirmar novamente.",
	),
	(
		"*Como faço para um irmão que cancelou confirmar novamente?*",
		"Basta ele acessar o evento novamente e clicar em 'Confirmar presença'. O bot vai registrar uma nova confirmação.",
	),
	(
		"*Posso usar o mesmo cadastro de loja para vários eventos?*",
		"*Sim!* Por isso é tão útil cadastrar sua loja. No fluxo oficial, ela pode ser usada como atalho. Na IA, o secretário já aproveita automaticamente a loja vinculada ao perfil.",
	),
	(
		"*Como faço para o endereço abrir no mapa?*",
		"No campo 'Endereço', cole um *link do Google Maps* em vez de escrever o endereço. O bot vai criar automaticamente um botão *'📍 Abrir no mapa'*.",
	),
	(
		"*O que significa 'VM' na lista de confirmados?*",
		"'VM' = *Venerável Mestre*. Durante o cadastro, o irmão informa se é Venerável Mestre. Quem responde 'Sim' aparece com 'VM' antes do nome na lista de confirmados.",
	),
	(
		"*Posso desativar as notificações de confirmação temporariamente?*",
		"Sim! Use o menu *'🔔 Configurar notificações'* na Área do Secretário e desative. Quando quiser voltar a receber, é só ativar novamente.",
	),
	(
		"*Apaguei a conversa com o bot, perdi tudo?*",
		"*Não se preocupe!* O bot guarda todas as informações na planilha. Basta digitar */bode* no grupo ou */start* no privado que ele recria o menu automaticamente.",
	),
	(
		"*Um irmão novo entrou no grupo, mas o bot não responde para ele*",
		"Isso acontece se o irmão *nunca iniciou conversa com o bot no privado*. Peça para ele: clicar no nome do bot no grupo; clicar em 'Enviar mensagem'; digitar qualquer coisa (ou */start*). Depois disso, o bot vai reconhecê-lo normalmente.",
	),
	(
		"*O bot parou de responder no meio do cadastro de um evento*",
		"Isso pode acontecer se você demorou muito para responder (mais de 24 horas). O cadastro expira por segurança. Basta começar de novo pelo fluxo oficial ou refazer o pedido no Assistente IA.",
	),
]

FAQ_NIVEL3 = [
	(
		"*Como criar sessão pela IA sendo administrador?*",
		"Você também pode descrever a sessão em linguagem natural. Se informar a loja na frase, o bot usa essa loja. Se não informar, o bot pedirá explicitamente a loja do evento antes de montar o rascunho.",
	),
	(
		"*Como promover um membro a secretário?*",
		"Na Área do Administrador, use a função 'Promover/Rebaixar' e siga as instruções.",
	),
	(
		"*Como editar os dados de qualquer membro?*",
		"Na Área do Administrador, use a função 'Editar membros' e selecione o membro desejado.",
	),
	(
		"*Posso ver todos os membros cadastrados no bot?*",
		"Sim, na Área do Administrador há uma opção para listar todos os membros.",
	),
	(
		"*O que acontece se eu rebaixar um secretário?*",
		"Ele perderá o acesso às funções de secretário, mas seus eventos já cadastrados permanecerão ativos. Ele não poderá criar novos eventos ou gerenciar os existentes.",
	),
	(
		"*Como o sistema de permissões funciona?*",
		"O bot consulta o cadastro do membro para determinar as funcionalidades acessíveis a cada usuário (1=comum, 2=secretário, 3=admin).",
	),
]


async def mostrar_faq(update, context):
	user_id = update.effective_user.id
	nivel = get_nivel(user_id)

	texto = TEXTO_FAQ_INICIAL + "\n\n"

	if nivel == "1":
		faqs_para_exibir = FAQ_NIVEL1
		titulo_faq = "👤 *Perguntas Frequentes - Membro Comum*"
	elif nivel == "2":
		faqs_para_exibir = FAQ_NIVEL2
		titulo_faq = "🔰 *Perguntas Frequentes - Secretário*"
	elif nivel == "3":
		faqs_para_exibir = FAQ_NIVEL3
		titulo_faq = "⚜️ *Perguntas Frequentes - Administrador*"
	else:
		faqs_para_exibir = FAQ_NIVEL1
		titulo_faq = "❓ *Perguntas Frequentes*"

	texto += titulo_faq + "\n\n"
	for i, (pergunta, resposta) in enumerate(faqs_para_exibir, start=1):
		texto += f"{i}. {pergunta}\n"
		texto += f"   {resposta}\n\n"

	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar à Central de Ajuda", callback_data="menu_ajuda")]]
	)

	await navegar_para(update, context, "Perguntas Frequentes", texto, teclado)
