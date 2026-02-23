def cadastrar_evento(dados: dict):
    sheet = conectar_sheets()
    aba = sheet.worksheet("Eventos")

    linha = [
        dados.get("data", ""),
        dados.get("dia_semana", ""),
        dados.get("nome_loja", ""),
        dados.get("numero_loja", ""),
        dados.get("oriente", ""),
        dados.get("grau", ""),
        dados.get("tipo_sessao", ""),
        dados.get("rito", ""),
        dados.get("potencia", ""),
        dados.get("traje", ""),
        dados.get("agape", ""),
        dados.get("observacoes", ""),
        dados.get("telegram_id_grupo", ""),
        dados.get("telegram_id_secretario", ""),
        dados.get("status", "Ativo"),
        dados.get("endereco", ""),
    ]

    aba.append_row(linha)
def buscar_membro(telegram_id: int):
    sheet = conectar_sheets()
    aba = sheet.worksheet("Membros")
    registros = aba.get_all_records()

    for registro in registros:
        if str(registro.get("Telegram ID", "")) == str(telegram_id):
            return registro
    return None