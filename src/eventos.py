# src/eventos.py
# ============================================
# BODE ANDARILHO - CANCELAMENTO DE PRESENÇA
# ============================================

async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa o cancelamento de presença."""
    query = update.callback_query
    data = query.data

    # CASO 1: Confirmação de cancelamento (passo 2)
    if data.startswith("confirma_cancelar|"):
        _, id_evento_cod = data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        logger.info(f"Processando confirmação de cancelamento: evento {id_evento}, usuário {user_id}")

        if cancelar_confirmacao(id_evento, user_id):
            # Feedback visual IMEDIATO
            if update.effective_chat.type in ["group", "supergroup"]:
                # No grupo: apaga a lista e mostra mensagem de confirmação
                try:
                    await query.delete_message()
                except Exception as e:
                    logger.error(f"Erro ao deletar mensagem: {e}")
                
                # Envia mensagem de confirmação no grupo
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="✅ *Presença cancelada com sucesso!*",
                    parse_mode="Markdown"
                )
            else:
                # No privado: edita a mensagem com confirmação
                await _enviar_ou_editar_mensagem(
                    context, user_id, TIPO_RESULTADO,
                    "❌ *Presença cancelada*\n\nSe mudar de ideia, basta confirmar novamente.",
                    limpar_conteudo=True
                )
            await query.answer("✅ Presença cancelada!")
        else:
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "Não foi possível cancelar. Você não estava confirmado para este evento.",
                limpar_conteudo=True
            )
        return

    # CASO 2: Pedido de cancelamento (passo 1)
    if data.startswith("cancelar|"):
        _, id_evento_cod = data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        logger.info(f"Processando pedido de cancelamento: evento {id_evento}, usuário {user_id}")

        # Se estiver em grupo, redireciona para o privado para confirmação
        if update.effective_chat.type in ["group", "supergroup"]:
            teclado = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar|{_encode_cb(id_evento)}"),
                InlineKeyboardButton("🔙 Não, voltar", callback_data=f"evento|{_encode_cb(id_evento)}")
            ]])
            await context.bot.send_message(
                chat_id=user_id,
                text="*Confirmar cancelamento da sua presença?*",
                parse_mode="Markdown",
                reply_markup=teclado
            )
            await query.answer("📨 Instruções enviadas no privado.")
            return

        # Se estiver no privado, já pode cancelar direto
        if cancelar_confirmacao(id_evento, user_id):
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "❌ *Presença cancelada*\n\nSe mudar de ideia, basta confirmar novamente.",
                limpar_conteudo=True
            )
        else:
            await _enviar_ou_editar_mensagem(
                context, user_id, TIPO_RESULTADO,
                "Não foi possível cancelar. Você não estava confirmado para este evento.",
                limpar_conteudo=True
            )
        return

    await _enviar_ou_editar_mensagem(
        context, update.effective_user.id, TIPO_RESULTADO,
        "Comando de cancelamento inválido.",
        limpar_conteudo=True
    )