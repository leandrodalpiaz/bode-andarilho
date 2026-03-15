# ============================================
# BODE ANDARILHO - CONSTANTES DE MENSAGENS
# ============================================
# 
# Este arquivo centraliza todas as mensagens textuais do bot.
# O tom é fraterno, comedido e utiliza terminologia maçónica
# para fortalecer os laços entre os obreiros.
# 
# ============================================

# ============================================
# BOAS-VINDAS E CADASTRO
# ============================================

BOAS_VINDAS = (
    "Saudações Fraternas, meu Irmão! 📜\n\n"
    "Bem-vindo ao *Bode Andarilho*. Sou o seu auxílio no fortalecimento da "
    "visitação e na organização das nossas agendas em Loja.\n\n"
    "Para que possamos caminhar juntos, peço que realize um breve cadastro. "
    "É um processo simples para que as Colunas o reconheçam."
)

BOAS_VINDAS_RETORNO = (
    "Saudações, Ir.·. {nome}! 🤝\n\n"
    "É uma alegria tê-lo novamente entre nós. Como posso auxiliar em seu "
    "trabalho ou em sua jornada de visitação hoje?"
)

MENU_PRINCIPAL = "Por favor, selecione a oficina ou a ação desejada no menu abaixo:"

CADASTRO_CONCLUIDO = (
    "✅ *Cadastro realizado a contento!*\n\n"
    "Os seus dados foram registados. Agora, use /start para aceder ao "
    "Painel do Obreiro e ver as sessões disponíveis."
)

CADASTRO_CANCELADO = (
    "Cadastro interrompido. Quando desejar retomar o seu lugar em nossa "
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
    "Caso os seus planos mudem e possa estar connosco, a sua confirmação será bem-vinda."
)

JA_CONFIRMOU = "Identificámos que já confirmou presença para este trabalho."

NAO_CONFIRMOU = "Não encontramos registo da sua confirmação para esta sessão."


# ============================================
# ÁREAS RESTRITAS
# ============================================

ACESSO_NEGADO = "⛔ Acesso restrito. Este grau de permissão não foi concedido ao seu perfil."

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
    "Saudações, Ir.·. {nome}! Amanhã teremos um encontro em Loja:\n\n"
    "🏛️ *Loja:* {loja}\n"
    "📅 *Data:* {data}\n"
    "🕐 *Horário:* {horario}\n"
    "📍 *Local:* {local}\n"
    "🔷 *Grau Mínimo:* {grau}\n"
    "👔 *Traje:* {traje}\n"
    "🍽️ *Ágape:* {agape}\n\n"
    "A sua presença fortalecerá a nossa egrégora! 🤝"
)

LEMBRETE_MEIO_DIA_TITULO = "🕛 *MEIO-DIA EM PONTO!*"

LEMBRETE_MEIO_DIA_CORPO = (
    "Ir.·. {nome}, o sol está no seu zénite. Hoje é dia de trabalho!\n\n"
    "🏛 *Loja {loja} nº {numero}*\n"
    "📍 {local}\n"
    "🕕 {horario}\n\n"
    "Encontramo-nos em breve no Templo! 🤝"
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
    "👤 *Guia do Membro*\n\n"
    "Aqui você encontra o básico para usar o Bode Andarilho como membro comum."
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
    "Aqui você encontrará guias detalhados para as principais funções do Bode Andarilho."
    "\n\n*(Conteúdo dos tutoriais a ser adicionado posteriormente.)*"
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