# ============================================
# BODE ANDARILHO - PERFIL DO USUÁRIO
# ============================================
# 
# Este módulo gerencia a exibição do perfil do usuário
# e oferece acesso à edição do próprio cadastro.
# 
# Funcionalidades:
# - Exibição dos dados cadastrais do membro
# - Botão para acessar a edição do perfil
# - Formatação amigável das informações
# 
# ============================================

from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.sheets_supabase import buscar_membro
from src.ajuda.conquistas import calcular_conquistas_membro
from src.bot import (
    navegar_para,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)


# ============================================
# FUNÇÕES AUXILIARES
# ============================================

def _formatar_data_nasc(data_str: str) -> str:
    """
    Tenta formatar data de nascimento de forma amigável (DD/MM/AAAA).
    """
    if not data_str:
        return "Não informada"
    
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(data_str.strip(), fmt)
            return dt.strftime("%d/%m/%Y")
        except:
            pass
    
    return data_str


# ============================================
# EXIBIÇÃO DO PERFIL
# ============================================

async def mostrar_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Exibe o perfil do usuário com opção de editar.
    
    Fluxo:
    - Se usuário não tem cadastro: oferece para iniciar cadastro
    - Se tem cadastro: mostra todos os dados formatados
    """
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if not membro:
        # Usuário não tem cadastro
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Realizar Registro", callback_data="iniciar_cadastro")],
            [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
        ])
        
        await navegar_para(
            update, context,
            "Meu Perfil",
            "👤 *Meu Registro*\n\nVocê ainda não possui um registro regular.\nSeus dados permanecem sempre *acobertos* por segurança.\n\nClique abaixo para iniciar:",
            teclado
        )
        return

    # Extração de dados com suporte a diferentes nomes de colunas
    nome = membro.get("Nome") or membro.get("nome") or "Não informado"
    data_nasc = _formatar_data_nasc(membro.get("Data de nascimento") or membro.get("data_nasc") or "")
    grau = membro.get("Grau") or membro.get("grau") or "Não informado"
    loja = membro.get("Loja") or membro.get("loja") or "Não informado"
    numero_loja = membro.get("Número da loja") or membro.get("numero_loja") or ""
    oriente = membro.get("Oriente") or membro.get("oriente") or "Não informado"
    potencia = membro.get("Potência") or membro.get("potencia") or "Não informado"
    vm = membro.get("Venerável Mestre") or membro.get("veneravel_mestre") or membro.get("vm") or "Não"
    mi = membro.get("Mestre Instalado") or membro.get("mestre_instalado") or membro.get("mi") or "Não"
    nivel = str(membro.get("Nivel") or "1")

    # Texto amigável para o nível de permissão
    niveis = {"1": "Obreiro", "2": "Secretário", "3": "Administrador"}
    nivel_texto = niveis.get(nivel, "Obreiro")

    # Formatação do número da loja se existir
    numero_fmt = f" - Nº {numero_loja}" if numero_loja and str(numero_loja) not in ("0", "Não informado") else ""

    # 1. Montar dados cadastrais
    corpo_perfil = (
        f"👤 *Meu Perfil*\n\n"
        f"*Nome:* {nome}\n"
        f"*Data de nascimento:* {data_nasc}\n"
        f"*Grau:* {grau}\n"
        f"*Mestre Instalado:* {mi}\n"
        f"*Loja:* {loja}{numero_fmt}\n"
        f"*Oriente:* {oriente}\n"
        f"*Potência:* {potencia}\n"
        f"*Venerável Mestre:* {vm}\n"
        f"*Nível de acesso:* {nivel_texto}\n"
        f"*Permissões:* consultar sessões, confirmar presença e atualizar seus dados.\n"
    )

    # 2. Carregar Conquistas reais do Supabase
    from src.conquistas import CONQUISTAS, verificar_novas_conquistas
    from src.sheets_supabase import listar_conquistas_obtidas
    
    # --- GATILHO ASSÍNCRONO DE VERIFICAÇÃO DE CONQUISTAS ---
    try:
        await verificar_novas_conquistas(user_id, context.bot)
    except Exception as ev_err:
        logger.warning("Falha silenciosa ao apurar novas conquistas: %s", ev_err)
        
    slugs_obtidos = listar_conquistas_obtidas(user_id) or []
    
    ordem_hierarquia = [
        "rs", "rc", "pj", "ce", "e9", "og", "mp", "na", "ic", "pm", "io"
    ]
    
    titulo_destaque = "Iniciando Caminhada"
    for s in ordem_hierarquia:
        if s in slugs_obtidos:
            meta = CONQUISTAS.get(s)
            if meta:
                titulo_destaque = meta["nome"]
            break
            
    cabecalho_nivel = f"Seu Nível de Andarilho: *{titulo_destaque}* 🐐\n\n"
    texto = cabecalho_nivel + corpo_perfil
    
    if slugs_obtidos:
        texto += "\n*🏆 Minhas Medalhas Digitais:*\n"
        linhas_medalhas = []
        for s in slugs_obtidos:
            meta = CONQUISTAS.get(s)
            if meta:
                linhas_medalhas.append(f"🏅 *{meta['nome']}*: {meta['descricao']}")
        texto += "\n".join(linhas_medalhas)
    else:
        texto += "\n_Você ainda não possui medalhas na sua Jornada do Obreiro._"

    # --- RITO DE FUNDACAO BOTÃO INTENCAO ---
    botoes_perfil = [[InlineKeyboardButton("✏️ Editar Perfil", callback_data="editar_perfil")]]
    
    is_nivel_1 = str(membro.get("Nivel") or membro.get("nivel") or "1") == "1"
    loja_man = membro.get("Loja Manual") or membro.get("loja_manual")
    
    if is_nivel_1 and loja_man:
        botoes_perfil.append([InlineKeyboardButton("🏛️ Quero Gerenciar minha Oficina", callback_data="fundacao_solicitar")])
        
    botoes_perfil.append([InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_principal")])
    teclado = InlineKeyboardMarkup(botoes_perfil)

    # Geração do Diploma Digital Heráldico (Coluna 4)
    try:
        query = update.callback_query
        if query:
            try:
                await query.answer("Preparando Diploma... 📜", show_alert=False)
            except Exception:
                pass
        
        from src.render_diploma import renderizar_diploma
        
        # Passa os dados estruturados do membro e as conquistas reais
        caminho_diploma = renderizar_diploma(membro, slugs_obtidos)
        
        if caminho_diploma and os.path.exists(caminho_diploma):
            # Se disparado via clique em botão, apagamos o menu anterior para evitar poluição
            query = update.callback_query
            if query:
                try:
                    await query.message.delete()
                except Exception:
                    pass
            
            # Envia o pergaminho visual
            with open(caminho_diploma, "rb") as photo:
                msg_diploma = await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption="📜 *Diploma do Andarilho - Jornada do Obreiro*\n\n"
                            "Suas medalhas, dados e visto oficial da Chancelaria.",
                    parse_mode="Markdown",
                    reply_markup=teclado
                )
                
            # Registra o ID da mensagem no rastreador global de navegação para limpeza futura automática
            from src.bot import estado_mensagens
            if user_id not in estado_mensagens:
                estado_mensagens[user_id] = {}
            
            estado_mensagens[user_id][TIPO_RESULTADO] = {
                "message_id": msg_diploma.message_id,
                "content_hash": None  # Evita colisão de hash e força renderização
            }
            
            # Remove arquivo temporário de forma segura após envio
            try:
                os.remove(caminho_diploma)
            except Exception:
                pass
                
            return
            
    except Exception as err:
        logger.error("Falha ao gerar ou enviar diploma digital: %s. Usando fallback textual.", err)

    # Fallback seguro: Envia a tela puramente textual se houver qualquer erro na imagem
    await navegar_para(
        update, context,
        "Meu Perfil",
        texto,
        teclado
    )
