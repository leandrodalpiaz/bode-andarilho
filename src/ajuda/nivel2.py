from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_GUIA_SECRETARIO


async def guia_nivel2(update, context):
	texto = TEXTO_GUIA_SECRETARIO + "\n\n"
	texto += "*1. Cadastrar Nova Loja:*\n"
	texto += "   Na 'Área do Secretário', clique em '🏛️ Minhas lojas' > '➕ Cadastrar nova loja' para pré-cadastrar os dados fixos da sua loja e agilizar a criação de eventos.\n\n"
	texto += "*2. Criar uma Sessão:*\n"
	texto += "   Na 'Área do Secretário', clique em '📌 Cadastrar evento'. Você pode usar os dados de uma loja pré-cadastrada como atalho. O bot publicará a sessão automaticamente no grupo.\n\n"
	texto += "*3. Gerenciar Meus Eventos:*\n"
	texto += "   Em '📋 Meus eventos', você pode ver os eventos que criou e acessar opções como '📊 Resumo da sessão', '✏️ Editar evento', '👥 Ver confirmados', '📋 Copiar lista de confirmados' e '❌ Cancelar evento'.\n\n"
	texto += "*4. Ver Lista de Confirmados:*\n"
	texto += "   Nos detalhes de um evento, clique em '👥 Ver confirmados' para ver a lista completa de irmãos que confirmaram presença, incluindo grau, loja, oriente e se vão com ágape.\n\n"
	texto += "*5. Copiar Lista para Ágape:*\n"
	texto += "   Em 'Meus eventos', escolha o evento e clique em '📋 Copiar lista de confirmados'. O bot gera um texto formatado que você pode copiar e colar para compartilhar com quem organiza o ágape.\n\n"
	texto += "*6. Configurar Notificações:*\n"
	texto += "   Na 'Área do Secretário', em '🔔 Configurar notificações', você pode ativar ou desativar os avisos no privado sobre novas confirmações nos seus eventos."

	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("🏛️ Cadastrar nova Loja", callback_data="ajuda_nivel2_cadastrar_loja")],
			[InlineKeyboardButton("📅 Criar uma sessão", callback_data="ajuda_nivel2_criar_sessao")],
			[InlineKeyboardButton("📋 Gerenciar meus eventos", callback_data="ajuda_nivel2_gerenciar_eventos")],
			[InlineKeyboardButton("👥 Ver lista de confirmados", callback_data="ajuda_nivel2_ver_confirmados")],
			[InlineKeyboardButton("📋 Copiar lista para ágape", callback_data="ajuda_nivel2_copiar_lista")],
			[InlineKeyboardButton("🔔 Configurar notificações", callback_data="ajuda_nivel2_notificacoes")],
			[InlineKeyboardButton("🔙 Voltar à Central de Ajuda", callback_data="menu_ajuda")],
		]
	)

	await navegar_para(update, context, "Guia do Secretário", texto, teclado)


async def ajuda_nivel2_cadastrar_loja(update, context):
	texto = (
		"*Como Cadastrar uma Nova Loja:*\n\n"
		"1. Na 'Área do Secretário', clique em '🏛️ Minhas lojas'.\n"
		"2. Em seguida, clique em '➕ Cadastrar nova loja'.\n"
		"3. O bot pedirá informações como Nome, Número, Rito, Potência e Endereço da loja. Preencha-as cuidadosamente.\n"
		"4. Ao final, confirme os dados. Esta loja ficará salva para ser usada como atalho na criação de eventos."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Secretário", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Cadastrar Loja", texto, teclado)


async def ajuda_nivel2_criar_sessao(update, context):
	texto = (
		"*Como Criar uma Sessão (Evento):*\n\n"
		"1. Na 'Área do Secretário', clique em '📌 Cadastrar evento'.\n"
		"2. Se você já tem lojas cadastradas, o bot perguntará se deseja usar uma delas como atalho para preencher alguns dados automaticamente.\n"
		"3. Siga as perguntas do bot, fornecendo detalhes como data, horário, grau mínimo, tipo de sessão, traje, ágape e observações.\n"
		"4. Após revisar o resumo, clique em '✅ Confirmar publicação'. O evento será publicado no grupo da loja."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Secretário", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Criar Sessão", texto, teclado)


async def ajuda_nivel2_gerenciar_eventos(update, context):
	texto = (
		"*Como Gerenciar Seus Eventos:*\n\n"
		"1. Na 'Área do Secretário', clique em '📋 Meus eventos'.\n"
		"2. Escolha o evento que deseja gerenciar na lista.\n"
		"3. Você terá opções como:\n"
		"   - *'📊 Resumo da sessão':* Para uma visão rápida das confirmações.\n"
		"   - *'✏️ Editar evento':* Para alterar detalhes do evento (atenção: edições removem confirmações).\n"
		"   - *'👥 Ver confirmados':* Para ver a lista completa de participantes.\n"
		"   - *'📋 Copiar lista de confirmados':* Para gerar um texto fácil de compartilhar.\n"
		"   - *'❌ Cancelar evento':* Para desmarcar a sessão (atenção: ação irreversível)."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Secretário", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Gerenciar Eventos", texto, teclado)


async def ajuda_nivel2_ver_confirmados(update, context):
	texto = (
		"*Como Ver a Lista de Confirmados:*\n\n"
		"1. Em '📋 Meus eventos', escolha o evento desejado.\n"
		"2. Clique em '👥 Ver confirmados'.\n"
		"3. O bot exibirá uma lista detalhada com o nome, grau, loja, oriente, potência e status de ágape de cada irmão que confirmou presença. 'VM' indica Venerável Mestre."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Secretário", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Ver Confirmados", texto, teclado)


async def ajuda_nivel2_copiar_lista(update, context):
	texto = (
		"*Como Copiar a Lista para Ágape:*\n\n"
		"1. Em '📋 Meus eventos', escolha o evento desejado.\n"
		"2. Clique em '📋 Copiar lista de confirmados'.\n"
		"3. O bot enviará uma mensagem com a lista formatada. Selecione o texto, copie e cole onde precisar (ex: WhatsApp para quem organiza o ágape)."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Secretário", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Copiar Lista", texto, teclado)


async def ajuda_nivel2_notificacoes(update, context):
	texto = (
		"*Como Configurar Notificações:*\n\n"
		"1. Na 'Área do Secretário', clique em '🔔 Configurar notificações'.\n"
		"2. Você verá o status atual (Ativadas/Desativadas).\n"
		"3. Escolha '📥 Ativar notificações' para receber avisos no privado sobre novas confirmações nos seus eventos, ou '🔕 Desativar notificações' para parar de recebê-los."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Secretário", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Configurar Notificações", texto, teclado)
