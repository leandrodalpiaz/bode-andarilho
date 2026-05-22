import re

def update_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    new_func = """def _parece_postagem_manual_sessao(texto: str, has_media: bool = False) -> bool:
    bruto = texto or ""
    lower = bruto.lower()
    
    if "?" in bruto:
        return False
    if "visit" in lower:
        return False
    if not has_media:
        return False

    gatilhos = [
        "sessão", "sessao", "evento", "grau", "loja", "oriente",
        "rito", "ágape", "agape", "traje", "ordem do dia",
    ]
    pontos = sum(1 for termo in gatilhos if termo in lower)
    import re
    tem_data = bool(re.search(r"\\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\\b", lower))
    tem_hora = bool(re.search(r"\\b\d{1,2}[:h]\d{2}\\b|\\b\d{1,2}h\\b", lower))
    tem_bloco = "\\n" in bruto and pontos >= 3
    return (tem_data and tem_hora and pontos >= 2) or tem_bloco"""
    
    content = re.sub(r'def _parece_postagem_manual_sessao\(texto: str\) -> bool:.*?return \(tem_data and tem_hora and pontos >= 2\) or tem_bloco', new_func, content, flags=re.DOTALL)
    
    if "texto_privado_router" in content:
        content = content.replace(
            'texto = (update.message.text or "").strip()',
            'texto = (update.message.text or update.message.caption or "").strip()\n    has_media = bool(update.message.photo or update.message.document)'
        )
        content = content.replace(
            'if _parece_postagem_manual_sessao(texto):',
            'if _parece_postagem_manual_sessao(texto, has_media):'
        )
        
    if "mensagem_grupo_handler" in content:
        content = content.replace(
            'text = (update.message.text or "").strip().lower()',
            'text = (update.message.text or update.message.caption or "").strip().lower()\n        has_media = bool(update.message.photo or update.message.document)'
        )
        content = content.replace(
            'if _parece_postagem_manual_sessao(update.message.text or ""):',
            'if _parece_postagem_manual_sessao(update.message.text or update.message.caption or "", has_media):'
        )
        
        content = content.replace(
            'filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND',
            'filters.ChatType.PRIVATE & (filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND'
        )
        content = content.replace(
            'filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND',
            'filters.ChatType.GROUPS & (filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND'
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

update_file("src/bot.py")
update_file("main.py")
