# ============================================
# BODE ANDARILHO - CONSTANTES DE MENSAGENS
# ============================================
# 
# Este arquivo centraliza todas as mensagens textuais do bot.
# O tom é fraterno, comedido e utiliza terminologia maçônica
# para fortalecer os laços entre os obreiros.
# 
# ============================================

# ============================================
# BOAS-VINDAS E REGISTRO
# ============================================

BOAS_VINDAS = (
    "Saudações Fraternas, meu Irmão! 📜\n\n"
    "Bem-vindo ao *Bode Andarilho*. Sou o seu auxílio no fortalecimento da "
    "visitação e na organização das nossas agendas em Loja.\n\n"
    "Para que possamos caminhar juntos, peço que realize um breve registro. "
    "É um processo simples para que as Colunas o reconheçam."
)

BOAS_VINDAS_RETORNO = (
    "Saudações, Ir.·. {nome}! 🤝\n\n"
    "É uma alegria tê-lo novamente entre nós. Como posso auxiliar em seu "
    "trabalho ou em sua jornada de visitação hoje?"
)

MENU_PRINCIPAL = "Por favor, selecione a oficina ou a ação desejada no menu abaixo:"

CADASTRO_CONCLUIDO = (
    "✅ *Registro realizado a contento!*\n\n"
    "Os seus dados foram registrados. Agora, use /start para acessar o "
    "Painel do Obreiro e ver as sessões disponíveis."
)

CADASTRO_CANCELADO = (
    "Registro interrompido. Quando desejar retomar o seu lugar em nossa "
    "oficina virtual, basta digitar /start."
)


# ============================================
# EVENTOS E CONFIRMAÇÕES
# ============================================

EVENTO_CADASTRADO = "✅ A sessão foi devidamente agendada e anunciada ao Quadro."

EVENTO_CANCELADO = (
    "✅ Sessão cancelada com sucesso.\n"
    "As confirmações de presença foram removidas e os irmãos serão notificados."
)

EVENTO_NAO_ENCONTRADO = "A sessão solicitada não foi encontrada ou já se encontra encerrada."

SEM_EVENTOS = "Não há sessões agendadas que correspondam aos critérios neste momento."

PRESENCA_CONFIRMADA = (
    "✅ Presença confirmada, Ir.·. {nome}!\n"
    "Que a sua visita contribua para o brilho dos nossos trabalhos."
)

PRESENCA_CANCELADA = (
    "❌ A sua presença foi removida da lista.\n\n"
    "Caso os seus planos mudem e possa estar conosco, a sua confirmação será bem-vinda."
)

JA_CONFIRMOU = "Identificamos que já confirmou presença para este trabalho."

NAO_CONFIRMOU = "Não encontramos registro da sua confirmação para esta sessão."


# ============================================
# ÁREAS RESTRITAS
# ============================================

ACESSO_NEGADO = "⛔ Acesso restrito. Este nível de acesso não foi concedido ao seu perfil."

APENAS_ADMIN = "Esta operação é exclusiva para os Administradores do sistema."

APENAS_SECRETARIO = (
    "Função reservada aos Irmãos Secretários ou Administradores para garantir "
    "a ordem dos trabalhos."
)


# ============================================
# LEMBRETES
# ============================================

LEMBRETE_TITULO = "🐐 *Lembrete de Visitação — Bode Andarilho*"

LEMBRETE_CORPO = (
    "Ir.·., passando para lembrar de sua presença confirmada amanhã ({data}) às {horario} na Loja {loja}. "
    "Caso tenha havido algum imprevisto, pedimos a gentileza de cancelar até hoje para evitar desperdícios. 🐐"
)

LEMBRETE_MEIO_DIA_TITULO = "🕛 *MEIO-DIA EM PONTO!*"

LEMBRETE_MEIO_DIA_CORPO = (
    "Meio dia em ponto!\n\n"
    "Hoje é dia de trabalho! Sua presença está confirmada para as {horario} na Loja {loja}. "
    "Desejamos uma profícua sessão. T.·.F.·.A.·. 🐐"
)

LEMBRETE_SECRETARIO_TITULO = "📋 *CIRCULAR AO SECRETÁRIO*"

LEMBRETE_SECRETARIO_CORPO = (
    "Ir.·. {nome}, recordamos que é o responsável pela organização deste evento:\n\n"
    "🏛️ *Loja:* {loja}\n"
    "📅 *Data:* {data}\n"
    "🕐 *Horário:* {horario}\n"
    "👔 *Traje:* {traje}\n"
    "👥 *Confirmados:* {num_confirmados}\n\n"
    "Tudo pronto para uma sessão Justa e Perfeita? 🤝"
)

LEMBRETE_SECRETARIO_MEIO_DIA_TITULO = "🕛 *MEIO-DIA EM PONTO — CIRCULAR AO SECRETÁRIO*"

LEMBRETE_SECRETARIO_MEIO_DIA_CORPO = (
    "Ir.·. {nome}, hoje é dia da sessão que V.·. organiza!\n\n"
    "🏛 *Loja {loja} nº {numero}*\n"
    "📍 {local}\n"
    "🕕 {horario}\n\n"
    "👥 *Confirmados até agora: {num_confirmados}*\n\n"
    "Tudo pronto para uma sessão Justa e Perfeita? 🤝"
)

# ============================================
# NOTIFICAÇÕES
# ============================================

NOTIFICACAO_NOVA_CONFIRMACAO = (
    "📢 *A COLUNA AUMENTA*\n\n"
    "👤 *Irmão:* {nome}\n"
    "📅 *Sessão:* {data} - {loja}\n"
    "🍽 *Participação no Ágape:* {agape}\n"
)


# ============================================
# ERROS
# ============================================

ERRO_GENERICO = "❌ Houve um percalço técnico. Por favor, tente novamente em instantes."

ERRO_DADOS_NAO_ENCONTRADOS = "Erro: Não foi possível localizar as informações. Tente reiniciar a operação."

ERRO_PERMISSAO = "⛔ Não possui as credenciais necessárias para esta ação."


# ============================================
# CENTRAL DE AJUDA
# ============================================

TEXTO_MENU_AJUDA_PRINCIPAL = (
    "🧭 *CENTRAL DE AJUDA*\n\n"
    "Escolha o tipo de orientação:"
)

TEXTO_GUIA_MEMBRO = (
    "👤 *Guia do Obreiro*\n\n"
    "Aqui você encontra o básico para usar o Bode Andarilho como obreiro."
)

TEXTO_GUIA_SECRETARIO = (
    "🔰 *Guia do Secretário*\n\n"
    "Aqui você encontra as orientações para gerenciar eventos e lojas."
)

TEXTO_GUIA_ADMINISTRADOR = (
    "⚜️ *Guia do Administrador*\n\n"
    "Aqui você encontra as funcionalidades exclusivas para administradores."
)

TEXTO_SOBRE_BODE = (
    "🏛️ *SOBRE O BODE ANDARILHO*\n\n"
    "O Bode Andarilho é um bot para Telegram criado para incentivar a visitação "
    "entre lojas maçônicas de potências regulares. Ele simplifica a divulgação "
    "de sessões, a confirmação de presença e o planejamento para secretários.\n\n"
    "Nossa missão é fortalecer a cultura da visitação, quebrar barreiras "
    "tecnológicas e respeitar o ritual e a tradição maçônica, sempre com uma "
    "linguagem cordial, simples e motivadora.\n\n"
    "O bot não substitui o contato humano ou as formalidades do Templo, mas "
    "atua como um facilitador e lembrete amigo.\n\n"
    "Para mais informações, consulte a documentação completa ou fale com o "
    "administrador do seu grupo."
)

TEXTO_TUTORIAIS_INICIAL = (
    "📚 *TUTORIAIS*\n\n"
    "Aqui você encontra guias passo a passo para os fluxos mais importantes do Bode Andarilho."
    "\n\nEscolha um tema para abrir o tutorial completo."
)

TEXTO_GLOSSARIO_INICIAL = (
    "📖 *GLOSSÁRIO*\n\n"
    "Termos técnicos do bot e do Telegram para facilitar sua compreensão."
)

TEXTO_FAQ_INICIAL = (
    "❓ *PERGUNTAS FREQUENTES*\n\n"
    "Dúvidas comuns organizadas por nível de acesso."
)


# ============================================
# GAMIFICAÇÃO
# ============================================

TEXTO_CONQUISTAS_MEMBRO_INICIAL = (
    "🏆 *MINHAS CONQUISTAS DE ANDARILHO*\n\n"
    "Sua jornada de visitação é reconhecida! Veja seus títulos honoríficos:"
)

TEXTO_CONQUISTAS_SECRETARIO_INICIAL = (
    "✨ *MEUS MARCOS DE SECRETÁRIO*\n\n"
    "Seu empenho na organização de eventos é celebrado! Veja seus marcos de reconhecimento:"
)

TEXTO_CELEBRACAO_MENSAL = (
    "🎉 *CELEBRAÇÃO FRATERNA - MÊS DE {mes_referencia}!* 🎉\n\n"
    "Queridos irmãos, com alegria compartilhamos os frutos da nossa união no último mês!\n\n"
    "Em *{mes_referencia}*, o Bode Andarilho registrou um total de *{total_visitas} visitas* "
    "a sessões em *{total_lojas_diferentes} lojas diferentes*!\n\n"
    "Cada presença fortalece a nossa corrente e enriquece a nossa jornada.\n"
    "Que a chama da visitação continue acesa!\n\n"
    "#BodeAndarilho #FraternidadeEmAção"
)


# ============================================
# CADASTRO — FLUXO
# ============================================
# Mensagens do ConversationHandler de cadastro (src/cadastro.py)

# [CONTEXTO] Ao usar /cadastro em grupo; orienta para o privado
# [CANAL] Grupo (mensagem direta)
CADASTRO_REDIRECIONAR_PRIVADO = (
    "🔒 Para realizar seu registro, fale comigo no privado.\n\n"
    "Clique aqui: @BodeAndarilhoBot e envie /start"
)

# [CONTEXTO] Cadastro estava inativo após saída do grupo; solicita revalidação
# [CANAL] Privado
CADASTRO_REVALIDACAO_NECESSARIA = (
    "🔄 *Revalidação de registro necessária*\n\n"
    "Identificamos que seu cadastro estava inativo por saída do grupo.\n"
    "Para voltar ao uso normal, atualize seus dados agora.\n\n"
    "_Isso garante informações atuais para administração e secretaria._"
)

# [CONTEXTO] Membro possui dados parcialmente preenchidos; pode continuar ou recomeçar
# [CANAL] Privado
CADASTRO_PARCIAL_EM_ANDAMENTO = (
    "🧾 *Registro em andamento*\n\n"
    "Identifiquei dados já preenchidos do seu registro.\n"
    "Você pode continuar de onde parou ou recomeçar do início.\n\n"
    "_O processo tem 8 passos rápidos e você pode usar Voltar/Cancelar a qualquer momento._"
)

# [CONTEXTO] Novo membro vindo do grupo sem cadastro prévio
# [CANAL] Privado
CADASTRO_BOAS_VINDAS_GRUPO = (
    "🐐 *Seja bem-vindo ao Bode Andarilho!*\n\n"
    "Para seguir no sistema, primeiro vamos realizar seu registro.\n"
    "Toque em *Iniciar Registro* e eu te guiarei passo a passo.\n\n"
    "_Suas informações estão sob a proteção do sigilo maçônico._"
)

# [CONTEXTO] Tela inicial padrão de cadastro
# [CANAL] Privado
CADASTRO_INICIO_PADRAO = (
    "👤 *Registro*\n\n"
    "Aqui você pode iniciar ou atualizar seu registro.\n"
    "O fluxo é guiado em *8 passos* com exemplos em cada etapa.\n\n"
    "_Lembre-se: suas informações estão sob a proteção do sigilo maçônico._"
)

# [CONTEXTO] Início do fluxo de novo cadastro (passo 1); {etapa_nome} = _texto_etapa(NOME)
# [CANAL] Privado
CADASTRO_NOVO_INTRO_TMPL = (
    "🧾 *Novo registro iniciado*\n\n"
    "Vamos concluir em 8 passos rápidos.\n"
    "Use *Voltar* para corrigir qualquer dado e *Cancelar* se quiser sair.\n\n"
    "{etapa_nome}"
)

# [CONTEXTO] Início do fluxo de revalidação de cadastro (passo 1); {etapa_nome} = _texto_etapa(NOME)
# [CANAL] Privado
CADASTRO_REVALIDAR_INTRO_TMPL = (
    "✏️ *Atualizar registro*\n\n"
    "Vamos revisar seus dados em 8 passos para garantir que tudo esteja atualizado.\n\n"
    "{etapa_nome}"
)

# [CONTEXTO] Erro quando nome tem menos de 3 caracteres
# [CANAL] Privado
CADASTRO_ERRO_NOME_CURTO = (
    "❌ Nome muito curto.\n"
    "Envie seu *nome completo* (com pelo menos 3 caracteres)."
)

# [CONTEXTO] Erro de data de nascimento em formato inválido
# [CANAL] Privado
CADASTRO_ERRO_DATA_NASC = (
    "❌ Data inválida.\n"
    "Envie no formato *DD/MM/AAAA* (ex.: 25/03/1988)."
)

# [CONTEXTO] Erro quando nome de loja está em branco
# [CANAL] Privado
CADASTRO_ERRO_LOJA = "❌ Informe o *nome da sua loja*:"

# [CONTEXTO] Erro quando número de loja não é inteiro
# [CANAL] Privado
CADASTRO_ERRO_NUMERO_LOJA = "❌ Número inválido. Envie somente números (ex.: 0, 12, 345)."

# [CONTEXTO] Erro quando oriente está em branco
# [CANAL] Privado
CADASTRO_ERRO_ORIENTE = "❌ Informe o *Oriente*:"

# [CONTEXTO] Erro quando potência está em branco
# [CANAL] Privado
CADASTRO_ERRO_POTENCIA = "❌ Informe a *Potência*:"

# [CONTEXTO] Grau digitado por texto não reconhecido; reexibe botões
# [CANAL] Privado
CADASTRO_ERRO_GRAU_TEXTO = (
    "Não reconheci esse grau.\n\n"
    "Selecione nos botões abaixo ou digite exatamente:"
    " *Aprendiz*, *Companheiro*, *Mestre* ou *Mestre Instalado*."
)

# [CONTEXTO] Resposta de VM por texto inválida (não é Sim/Não)
# [CANAL] Privado
CADASTRO_ERRO_VM_TEXTO = "Resposta inválida. Selecione *Sim* ou *Não* nos botões abaixo."

# [CONTEXTO] Callback de grau retornou dados inválidos (erro interno)
# [CANAL] Privado
CADASTRO_ERRO_GRAU_INVALIDO = "❌ Opção inválida. Selecione seu grau novamente:"

# [CONTEXTO] Grau selecionado via botão não é uma opção reconhecida
# [CANAL] Privado
CADASTRO_ERRO_GRAU_SELECIONE = "❌ Opção inválida. Selecione seu grau:"

# [CONTEXTO] Callback de VM retornou dados inválidos
# [CANAL] Privado
CADASTRO_ERRO_VM_INVALIDO = "❌ Opção inválida. Você é Venerável Mestre?"

# [CONTEXTO] Tela de revisão final antes de confirmar; {resumo} = _resumo_cadastro(context)
# [CANAL] Privado
CADASTRO_REVISAO_FINAL_TMPL = (
    "✅ *Revisão final*\n"
    "Confira os dados abaixo. Se estiver tudo certo, confirme o registro.\n\n"
    "{resumo}"
)

# [CONTEXTO] Ainda há campos obrigatórios não preenchidos; redireciona para etapa pendente
# [CANAL] Privado
CADASTRO_DADOS_PENDENTES = (
    "⚠️ Ainda faltam alguns dados antes da conclusão."
    " Vou te levar para a próxima etapa pendente."
)

# [CONTEXTO] Falha ao salvar o cadastro no banco de dados
# [CANAL] Privado
CADASTRO_FALHA_SALVAR = (
    "❌ Não consegui salvar seu registro agora.\n"
    "Tente confirmar novamente em instantes."
)

# [CONTEXTO] Prompt exibido quando confirmação é feita por texto em vez de botão
# [CANAL] Privado
CADASTRO_PROMPT_CONFIRMAR = (
    "Para concluir, toque em *✅ Confirmar registro* ou digite *confirmar*."
)

# [CONTEXTO] Fluxo de cadastro cancelado via botão "Cancelar"
# [CANAL] Privado
CADASTRO_OPERACAO_CANCELADA = "Operação cancelada."


# ============================================
# CONFIRMAÇÃO DE PRESENÇA — TEMPLATES
# ============================================
# Mensagens de confirmação/cancelamento (src/eventos.py)

# [CONTEXTO] Usuário sem cadastro tenta confirmar presença
# [CANAL] Privado
CONFIRMACAO_SEM_CADASTRO = "Irmão, antes de confirmar sua presença, preciso realizar seu registro."

# [CONTEXTO] Privado indisponível ao redirecionar para cadastro; alternativa no grupo
# [CANAL] Grupo
CONFIRMACAO_FALLBACK_GRUPO_CADASTRO = (
    "📩 Não consegui te chamar no privado para iniciar o registro.\n\n"
    "Toque no botão abaixo, abra meu chat e envie /start."
)

# [CONTEXTO] Toast/alert ao redirecionar para privado para completar cadastro
# [CANAL] Privado (toast)
CONFIRMACAO_CALLBACK_ABRIR_PRIVADO_CADASTRO = "Abra o privado do bot para concluir o registro."

# [CONTEXTO] Evento não encontrado ao tentar confirmar depois do cadastro
# [CANAL] Privado
CONFIRMACAO_SESSAO_NAO_ENCONTRADA = "Sessão não encontrada. Tente confirmar novamente."

# [CONTEXTO] Membro já confirmado; exibido no fluxo pós-cadastro
# [CANAL] Privado
CONFIRMACAO_JA_CONFIRMADO_POS_CADASTRO = "Você já estava confirmado para esta sessão."

# [CONTEXTO] Grau do irmão não corresponde ao grau da sessão; enviado no privado
# [CANAL] Privado
CONFIRMACAO_GRAU_INSUFICIENTE_TMPL = (
    "Esta é uma Sessão de Grau {grau_sessao}, Irmão.\n"
    "Confira seu grau cadastrado: {grau_cadastrado}."
)

# [CONTEXTO] Resposta ao secretário que confirma presença no próprio evento;
#            {nome},{data},{loja},{numero_fmt},{horario},{participacao},{bloco_importancia}
# [CANAL] Privado
CONFIRMACAO_SECRETARIO_TMPL = (
    "✅ *Presença confirmada, irmão {nome}!*\n\n"
    "Resumo:\n"
    "📅 {data} — {loja}{numero_fmt}\n"
    "🕕 Horário: {horario}\n"
    "🍽 {participacao}\n\n"
    "{bloco_importancia}"
    "📢 *Nova confirmação registrada*"
)

# [CONTEXTO] Confirmação de presença para membro com ágape;
#            {nome},{data},{loja},{numero_fmt},{horario},{participacao},{msg_agape}
# [CANAL] Privado
CONFIRMACAO_COM_AGAPE_TMPL = (
    "Ir.·., agradecemos sua visita! Presença CONFIRMADA (Com Ágape) para a sessão: {pauta} na Loja {loja}{numero_fmt}.\n\n"
    "📅 {data} às {horario}\n\n"
    "⚠️ Pedimos que cancelamentos sejam feitos com 24h de antecedência para nossa melhor organização.\n\n"
    "⚠️ A confirmação via bot não garante o ingresso no templo, ficam permanecidas às verificações habituais. 🐐"
)

# [CONTEXTO] Confirmação de presença para membro sem ágape;
#            {nome},{data},{loja},{numero_fmt},{horario},{participacao}
# [CANAL] Privado
CONFIRMACAO_SEM_AGAPE_TMPL = (
    "Ir.·., agradecemos sua visita! Presença CONFIRMADA (Sem Ágape) para a sessão: {pauta} na Loja {loja}{numero_fmt}.\n\n"
    "📅 {data} às {horario}\n\n"
    "⚠️ A confirmação via bot não garante o ingresso no templo, ficam permanecidas às verificações habituais. 🐐"
)

# [CONTEXTO] Mensagem sobre importância da confirmação de ágape (incluída na confirmação)
# [CANAL] Privado
MENSAGEM_CONFIRMACAO_AGAPE = (
    "Sua confirmação é muito importante! Ela nos ajuda a organizar tudo com carinho, "
    "evitando desperdícios e custos desnecessários.\n\n"
    "Fraterno abraço!"
)

# [CONTEXTO] Sucesso ao cancelar presença (enviado no grupo)
# [CANAL] Grupo
CANCELAR_PRESENCA_SUCESSO_GRUPO = "✅ *Presença cancelada com sucesso!*"

# [CONTEXTO] Pergunta de confirmação antes de cancelar presença (enviada no privado)
# [CANAL] Privado
CANCELAR_PRESENCA_CONFIRMAR = "*Confirmar cancelamento da sua presença?*"

# [CONTEXTO] Privado indisponível para cancelamento; alternativa no grupo
# [CANAL] Grupo
CANCELAR_PRESENCA_FALLBACK_GRUPO = (
    "📩 Não consegui enviar a confirmação de cancelamento no privado.\n\n"
    "Abra meu chat pelo botão abaixo e envie /start."
)

# [CONTEXTO] Toast/alert ao redirecionar para privado para confirmar cancelamento
# [CANAL] Privado (toast)
CANCELAR_PRESENCA_CALLBACK_ABRIR_PRIVADO = "Abra o privado do bot para concluir o cancelamento."

# [CONTEXTO] Toast/alert confirmando envio das instruções de cancelamento no privado
# [CANAL] Grupo (toast)
CANCELAR_PRESENCA_CALLBACK_INSTRUCOES = "📨 Instruções enviadas no privado."


# ============================================
# EDIÇÃO DE EVENTOS (SECRETÁRIO)
# ============================================
# Mensagens do fluxo de edição (src/eventos_secretario.py)

# [CONTEXTO] Dados de edição ausentes do contexto (user_data limpo)
# [CANAL] Privado
EDICAO_EVENTO_DADOS_NAO_ENCONTRADOS = "Erro: dados não encontrados. Tente novamente."

# [CONTEXTO] Dados do evento ausentes do contexto (user_data limpo)
# [CANAL] Privado
EDICAO_EVENTO_CONTEXTO_PERDIDO = "Erro: dados do evento não encontrados."

# [CONTEXTO] Campo do evento atualizado com sucesso; {campo_nome} = nome legível do campo
# [CANAL] Privado
EDICAO_EVENTO_SUCESSO_TMPL = "✅ {campo_nome} atualizado com sucesso!\n\nUse o menu acima para continuar."

# [CONTEXTO] Falha ao atualizar o campo no banco de dados
# [CANAL] Privado
EDICAO_EVENTO_FALHA = "❌ Erro ao atualizar o campo. Tente novamente mais tarde."

# [CONTEXTO] Fluxo de edição de evento cancelado
# [CANAL] Privado
EDICAO_EVENTO_CANCELADA = "Edição cancelada."


# ============================================
# MENSAGENS DE GRUPO E ONBOARDING
# ============================================
# Mensagens exibidas em grupos e no onboarding de novos membros (main.py)

# [CONTEXTO] Enviado no privado a membro sem cadastro que usou "bode" no grupo
# [CANAL] Privado
GRUPO_ONBOARDING_SEM_CADASTRO = (
    "👋 *Bem-vindo ao Bode Andarilho!*\n\n"
    "Para começar de forma simples e segura, toque em *Iniciar Registro* no privado."
)

# [CONTEXTO] Alternativa no grupo quando o privado estiver indisponível; botão com link para o privado
# [CANAL] Grupo
GRUPO_FALLBACK_ABRIR_PRIVADO = "📩 Para continuar, abra meu privado pelo botão abaixo."

# [CONTEXTO] Resposta no grupo para /start ou /cadastro
# [CANAL] Grupo
GRUPO_COMANDO_PRIVADO = "📩 Use o bot no privado para o registro e menus."

# [CONTEXTO] Resposta no grupo para comandos não reconhecidos (auto-apagada em 15 s)
# [CANAL] Grupo
GRUPO_COMANDO_NAO_RECONHECIDO = (
    "🛠️ Não reconheci esse comando no grupo.\n\n"
    "Aqui eu respondo apenas:\n"
    "• bode\n"
    "• /bode\n"
    "• menu\n"
    "• /menu\n"
    "• painel\n"
    "• /painel\n\n"
    "Para o registro e funções completas, fale comigo no privado."
)

# [CONTEXTO] Boas-vindas de retorno enviado no privado ao membro com cadastro ativo;
#            {nome} = membro.get('Nome', nome)
# [CANAL] Privado
GRUPO_BOAS_VINDAS_RETORNO_TMPL = (
    "Saudações, Ir.·. {nome}! 🤝\n\n"
    "Bem-vindo de volta ao grupo. Seu registro está regular.\n"
    "Digite *bode* no grupo ou use /start aqui para acessar o painel."
)

# [CONTEXTO] Onboarding enviado no privado ao novo membro que entrou no grupo; {nome}
# [CANAL] Privado
GRUPO_ONBOARDING_NOVO_MEMBRO_TMPL = (
    "Salve, {nome}! 🐐\n\n"
    "Bem-vindo ao *Bode Andarilho*.\n\n"
    "Para acessar as sessões e confirmar presenças, complete o seu "
    "registro. É rápido e seus dados ficam protegidos aqui no privado.\n\n"
    "Toque no botão abaixo para começar:"
)

# [CONTEXTO] Alternativa mínima no grupo quando o privado estiver indisponível para novo membro;
#            {nome} (auto-apagada em 30 s)
# [CANAL] Grupo
GRUPO_FALLBACK_NOVO_MEMBRO_TMPL = "Salve, {nome}! 🐐 Para realizar seu registro, toque no botão abaixo."
