from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_GUIA_ADMINISTRADOR


async def guia_nivel3(update, context):
	texto = TEXTO_GUIA_ADMINISTRADOR + "\n\n"
	texto += "*1. Promover/Rebaixar Membros:*\n"
	texto += "   Na 'Área do Administrador', você pode conceder ou remover o nível de 'Secretário' para outros membros, controlando quem pode cadastrar e gerenciar eventos.\n\n"
	texto += "*2. Editar Membros:*\n"
	texto += "   Acesse a função 'Editar membros' para alterar os dados de cadastro de qualquer membro do bot, incluindo nome, grau, loja, etc.\n\n"
	texto += "*3. Ver Todos os Membros:*\n"
	texto += "   Tenha uma visão completa de todos os membros cadastrados no bot, seus níveis de acesso e informações de contato.\n\n"
	texto += "*4. Gerenciar Permissões:*\n"
	texto += "   O administrador tem controle total sobre os níveis de acesso (comum, secretário, admin), garantindo a segurança e a organização do sistema."

	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("🔄 Promover/Rebaixar", callback_data="ajuda_nivel3_promover_rebaixar")],
			[InlineKeyboardButton("✏️ Editar membros", callback_data="ajuda_nivel3_editar_membros")],
			[InlineKeyboardButton("👥 Ver todos os membros", callback_data="ajuda_nivel3_ver_membros")],
			[InlineKeyboardButton("⚙️ Gerenciar permissões", callback_data="ajuda_nivel3_gerenciar_permissoes")],
			[InlineKeyboardButton("🔙 Voltar à Central de Ajuda", callback_data="menu_ajuda")],
		]
	)

	await navegar_para(update, context, "Guia do Administrador", texto, teclado)


async def ajuda_nivel3_promover_rebaixar(update, context):
	texto = (
		"*Como Promover/Rebaixar Membros:*\n\n"
		"Na 'Área do Administrador', você encontrará a opção para 'Promover/Rebaixar'.\n"
		"1. Selecione o membro desejado.\n"
		"2. Escolha se deseja promovê-lo a Secretário (Nível 2) ou rebaixá-lo para Membro Comum (Nível 1).\n"
		"Esta ação altera o campo 'Nível' na planilha 'Membros'."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Administrador", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Promover/Rebaixar", texto, teclado)


async def ajuda_nivel3_editar_membros(update, context):
	texto = (
		"*Como Editar Membros:*\n\n"
		"Na 'Área do Administrador', selecione 'Editar membros'.\n"
		"1. Escolha o membro cujos dados deseja alterar.\n"
		"2. O bot apresentará os campos editáveis (nome, grau, loja, etc.).\n"
		"3. Digite o novo valor para o campo selecionado. Esta função permite corrigir informações de qualquer membro."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Administrador", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Editar Membros", texto, teclado)


async def ajuda_nivel3_ver_membros(update, context):
	texto = (
		"*Como Ver Todos os Membros:*\n\n"
		"A 'Área do Administrador' oferece uma opção para 'Ver todos os membros'.\n"
		"Esta função lista todos os usuários cadastrados no bot, exibindo suas informações básicas e nível de acesso. É útil para uma visão geral da base de usuários."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Administrador", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Ver Todos os Membros", texto, teclado)


async def ajuda_nivel3_gerenciar_permissoes(update, context):
	texto = (
		"*Como Gerenciar Permissões:*\n\n"
		"O sistema de permissões do Bode Andarilho é baseado em níveis de acesso:\n"
		" - *Nível 1 (Comum):* Acesso básico (ver eventos, confirmar presença, perfil).\n"
		" - *Nível 2 (Secretário):* Acesso Nível 1 + cadastro e gestão de eventos, edição de membros comuns.\n"
		" - *Nível 3 (Administrador):* Acesso total, incluindo promoção/rebaixamento e edição de qualquer membro.\n\n"
		"O administrador gerencia esses níveis para controlar as funcionalidades disponíveis para cada usuário."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Administrador", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Gerenciar Permissões", texto, teclado)
