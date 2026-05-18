# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import tempfile
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

# Diretórios de assets
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BRANDING_DIR = ASSETS_DIR / "branding"

DEFAULT_TEXT_COLOR = (58, 36, 16, 255)  # Castanho envelhecido elegante
GOLD_TEXT_COLOR = (235, 195, 100, 230)   # Dourado queimado para relevos
GRAY_TEXT_COLOR = (120, 120, 120, 255)

def _load_custom_font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Tenta carregar fonte do diretório assets, senão usa fallback."""
    path = FONTS_DIR / name
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            pass
    # Fallbacks de sistema padrão
    fallbacks = ["georgia.ttf", "Georgia.ttf", "times.ttf", "Times New Roman.ttf"]
    for f in fallbacks:
        try:
            return ImageFont.truetype(f, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]

def _draw_centered(draw: ImageDraw.ImageDraw, text: str, center_x: int, y: int, font: ImageFont.ImageFont, fill: Tuple[int, int, int, int]) -> int:
    draw.text((center_x, y), text, font=font, fill=fill, anchor="ma")
    _, h = _measure_text(draw, "Ag", font)
    return y + h

def _wrap_and_draw_centered(draw: ImageDraw.ImageDraw, text: str, center_x: int, y: int, font: ImageFont.ImageFont, fill: Tuple[int, int, int, int], max_width: int, line_gap: int = 5) -> int:
    words = str(text).split()
    lines = []
    current = []
    for w in words:
        candidate = " ".join(current + [w])
        tw, _ = _measure_text(draw, candidate, font)
        if tw <= max_width:
            current.append(w)
        else:
            lines.append(" ".join(current))
            current = [w]
    if current:
        lines.append(" ".join(current))
        
    cy = y
    for line in lines:
        cy = _draw_centered(draw, line, center_x, cy, font, fill) + line_gap
    return cy

def _criar_fallback_pergaminho_vertical(width: int, height: int, bg_path: Path) -> Image.Image:
    """
    Se o template vertical personalizado não existir, criamos um pergaminho vertical
    9:16 fazendo o recorte central inteligente do original diploma_pergaminho_bg.png.
    """
    if bg_path.exists():
        try:
            bg_original = Image.open(bg_path).convert("RGBA")
            orig_w, orig_h = bg_original.size
            # Calcula recorte de largura proporcional a 9:16 com base na altura original
            target_w = int(orig_h * (9/16))
            left = (orig_w - target_w) // 2
            cropped = bg_original.crop((left, 0, left + target_w, orig_h))
            return cropped.resize((width, height), Image.Resampling.LANCZOS)
        except Exception as e:
            logger.warning("Falha ao recortar pergaminho horizontal: %s", e)
            
    # Fallback total sólido de cor pergaminho com bordas simuladas
    fallback = Image.new("RGBA", (width, height), (242, 230, 205, 255))
    draw = ImageDraw.Draw(fallback)
    draw.rectangle([20, 20, width-20, height-20], outline=(184, 134, 11, 255), width=8)
    draw.rectangle([28, 28, width-28, height-28], outline=(101, 67, 33, 255), width=2)
    return fallback

def renderizar_diploma(membro: Dict[str, Any], conquistas_obtidas: List[str], progressos: Dict[str, int]) -> List[str]:
    """
    Gera duas páginas independentes em proporção 9:16 (1080x1920) e as salva na pasta temp.
    Retorna uma lista contendo os caminhos absolutos dos arquivos [p1_path, p2_path].
    """
    width, height = 1080, 1920
    bg_horizontal_path = BRANDING_DIR / "diploma_pergaminho_bg.png"
    p1_template_path = BRANDING_DIR / "diploma_vertical_p1.png" # Arte espetacular enviada pelo usuário
    
    # ============================================
    # PÁGINA 1: DIPLOMA OFICIAL (CAPA SOLENE)
    # ============================================
    if p1_template_path.exists():
        p1 = Image.open(p1_template_path).convert("RGBA")
        p1 = p1.resize((width, height), Image.Resampling.LANCZOS)
    else:
        logger.warning(f"Capa personalizada {p1_template_path} não encontrada. Usando fallback recortado.")
        p1 = _criar_fallback_pergaminho_vertical(width, height, bg_horizontal_path)
        
    draw_p1 = ImageDraw.Draw(p1)
    center_x = width // 2
    
    # Fontes Premium
    font_nome = _load_custom_font("CormorantGaramond-SemiBold.ttf", 62)
    font_grau = _load_custom_font("CormorantGaramond-Italic.ttf", 36)
    font_assinatura = _load_custom_font("CormorantGaramond-Italic.ttf", 40)
    font_meta = _load_custom_font("CormorantGaramond-SemiBold.ttf", 28)
    
    # 1. Nome do Obreiro (Posicionado cirurgicamente no espaço central dourado)
    nome_membro = str(membro.get("Nome", membro.get("nome", "Ir.·. Obreiro"))).strip().upper()
    y_nome = 880
    _draw_centered(draw_p1, nome_membro, center_x, y_nome, font_nome, DEFAULT_TEXT_COLOR)
    
    # 2. Grau e Oficina
    grau = str(membro.get("Grau", membro.get("grau", "Aprendiz"))).strip()
    loja = str(membro.get("Loja", membro.get("loja", "Loja não informada"))).strip()
    num_loja = str(membro.get("Número da loja", membro.get("numero_loja", ""))).strip()
    loja_texto = f"{loja}, nº {num_loja}" if num_loja and num_loja != "0" else loja
    
    y_grau = y_nome + 75
    _draw_centered(draw_p1, f"Grau: {grau}  |  Oficina: {loja_texto}", center_x, y_grau, font_grau, (90, 65, 40, 230))
    
    # 3. Rodapé Oficial
    y_base = 1760
    _draw_centered(draw_p1, "Bode Andarilho :.", center_x - 280, y_base, font_assinatura, (60, 45, 30, 220))
    
    # Injeta a magnífica chancela de cera vermelha centralizada no rodapé
    seal_bode_path = BRANDING_DIR / "selo_bode_cera.png"
    if seal_bode_path.exists():
        try:
            seal_img = Image.open(seal_bode_path).convert("RGBA")
            seal_size = 200
            seal_img = seal_img.resize((seal_size, seal_size), Image.Resampling.LANCZOS)
            # Centralizado no meio exato entre as assinaturas
            p1.alpha_composite(seal_img, (center_x - seal_size // 2, y_base - 100))
        except Exception as e_seal:
            logger.warning("Falha ao inserir chancela oficial na Capa: %s", e_seal)
            
    oriente = str(membro.get("Oriente", membro.get("oriente", "Torres/RS"))).strip()
    _draw_centered(draw_p1, f"Oriente de {oriente} - 2026", center_x + 280, y_base, font_meta, (60, 45, 30, 220))
    
    # Marca d'água de pendência estética
    status_aud = str(membro.get("status_auditoria") or membro.get("Status Auditoria") or "").strip()
    if status_aud == "Pendente_Identidade":
        stamp_layer = Image.new("RGBA", p1.size, (255, 255, 255, 0))
        draw_stamp = ImageDraw.Draw(stamp_layer)
        stamp_text = "AGUARDANDO VALIDAÇÃO"
        font_stamp = _load_custom_font("Cinzel-Regular.ttf", 60)
        draw_stamp.text((width//2, height//2), stamp_text, font=font_stamp, fill=(180, 40, 40, 75), anchor="mm")
        rotated_stamp = stamp_layer.rotate(30, resample=Image.Resampling.BICUBIC, center=(width//2, height//2))
        p1.alpha_composite(rotated_stamp)

    # ============================================
    # PÁGINA 2: QUADRO DE CONQUISTAS E MEDALHAS
    # ============================================
    p2 = _criar_fallback_pergaminho_vertical(width, height, bg_horizontal_path)
    draw_p2 = ImageDraw.Draw(p2)
    
    font_titulo_p2 = _load_custom_font("Cinzel-Regular.ttf", 44)
    font_sub_p2 = _load_custom_font("Cinzel-Regular.ttf", 26)
    font_corpo_p2 = _load_custom_font("CormorantGaramond-SemiBold.ttf", 28)
    font_conquista_titulo = _load_custom_font("Cinzel-Regular.ttf", 21)
    font_conquista_desc = _load_custom_font("CormorantGaramond-SemiBold.ttf", 18)
    
    # 1. Títulos
    y_cursor = 80
    y_cursor = _draw_centered(draw_p2, "Bode Andarilho", center_x, y_cursor, font_sub_p2, (110, 80, 50, 210)) + 5
    y_cursor = _draw_centered(draw_p2, "QUADRO DE HONRA E CONQUISTAS", center_x, y_cursor, font_titulo_p2, DEFAULT_TEXT_COLOR) + 40
    
    # 2. Bloco Central: Perfil de Cadastro (Mantém P1 limpa)
    box_left = 80
    box_top = y_cursor
    box_width = width - 160
    box_height = 240
    
    draw_p2.rounded_rectangle(
        [box_left, box_top, box_left+box_width, box_top+box_height], 
        radius=15, 
        fill=(235, 222, 192, 180), 
        outline=(139, 90, 43, 200), 
        width=2
    )
    
    _draw_centered(draw_p2, "PERFIL DE CADASTRO DO OBREIRO", center_x, box_top + 15, font_sub_p2, DEFAULT_TEXT_COLOR)
    
    col1_x = box_left + 40
    col2_x = box_left + box_width // 2 + 20
    text_y = box_top + 60
    
    potencia = str(membro.get("Potência", membro.get("potencia", "Não informado"))).strip()
    cpf = str(membro.get("CPF", membro.get("cpf", "Não informado"))).strip()
    email = str(membro.get("E-mail", membro.get("email", "Não informado"))).strip()
    rito = str(membro.get("Rito", membro.get("rito", "Não informado"))).strip()
    telefone = str(membro.get("Telefone", membro.get("telefone", "Não informado"))).strip()
    
    if len(cpf) > 10:
        cpf = f"{cpf[:3]}.***.***-{cpf[-2:]}"
    if "@" in email:
        parts = email.split("@")
        email = f"{parts[0][:3]}***@{parts[1]}"
        
    draw_p2.text((col1_x, text_y), f"Loja: {loja_texto}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    draw_p2.text((col1_x, text_y + 40), f"Potência: {potencia}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    draw_p2.text((col1_x, text_y + 80), f"CPF: {cpf}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    draw_p2.text((col1_x, text_y + 120), f"E-mail: {email}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    
    draw_p2.text((col2_x, text_y), f"Rito: {rito}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    draw_p2.text((col2_x, text_y + 40), f"Telefone: {telefone}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    draw_p2.text((col2_x, text_y + 80), f"Grau: {grau}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    draw_p2.text((col2_x, text_y + 120), f"Cidade: {oriente}", font=font_corpo_p2, fill=DEFAULT_TEXT_COLOR)
    
    y_cursor += box_height + 45
    
    # 3. Grade Dinâmica de Conquistas (2 colunas x 6 linhas)
    from src.conquistas import CONQUISTAS_INFO
    grid_items = list(CONQUISTAS_INFO.items())
    
    start_grid_y = y_cursor
    item_w = 420
    item_h = 135
    h_gap = 70
    v_gap = 25
    
    for idx, (slug, info) in enumerate(grid_items):
        row = idx // 2
        col = idx % 2
        
        ix = box_left + col * (item_w + h_gap)
        iy = start_grid_y + row * (item_h + v_gap)
        
        # Lógica de Progresso e Opacidade
        pct = progressos.get(slug, 0)
        adquirida = pct >= 100
        alpha = int(35 + (pct * 2.2))  # Opacidade dinâmica
        
        emoji = info.get("emoji", "🏅")
        titulo = info.get("titulo", "")
        desc = info.get("descricao", "")
        
        if len(titulo) > 22:
            titulo = f"{titulo[:20]}..."
            
        # Desenha ícone/emoji
        font_emoji = _load_custom_font("georgia.ttf", 36)
        draw_p2.text((ix, iy), emoji, font=font_emoji, fill=(0, 0, 0, alpha))
        
        # Título da conquista
        title_color = DEFAULT_TEXT_COLOR if adquirida else (110, 95, 75, alpha)
        draw_p2.text((ix + 55, iy + 4), titulo, font=font_conquista_titulo, fill=title_color)
        
        # Descrição wrapped
        desc_color = (80, 60, 40, alpha) if adquirida else (140, 125, 110, alpha)
        words = desc.split()
        lines = []
        curr = []
        for w in words:
            candidate = " ".join(curr + [w])
            tw, _ = _measure_text(draw_p2, candidate, font_conquista_desc)
            if tw < (item_w - 60):
                curr.append(w)
            else:
                lines.append(" ".join(curr))
                curr = [w]
        if curr:
            lines.append(" ".join(curr))
            
        dy = iy + 35
        for line in lines[:2]:
            draw_p2.text((ix + 55, dy), line, font=font_conquista_desc, fill=desc_color)
            dy += 22
            
        # Barra gráfica de progresso
        bar_x = ix + 55
        bar_y = iy + 90
        bar_w = item_w - 55
        bar_h = 6
        
        # Fundo da barra
        draw_p2.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill=(215, 205, 190, 255))
        # Preenchimento dinâmico
        fill_w = int(bar_w * (pct / 100))
        if fill_w > 0:
            bar_color = (205, 149, 12, 255) if adquirida else (139, 115, 85, 200)
            draw_p2.rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], fill=bar_color)
            
        # Rótulo de porcentagem
        txt_pct = f"{pct}%" if pct < 100 else "Concluído!"
        draw_p2.text((bar_x + bar_w - 5, bar_y + 10), txt_pct, font=font_conquista_desc, fill=desc_color, anchor="ra")
        
    y_cursor += 6 * (item_h + v_gap)
    
    # 4. Medalhões de Mascotes na base (Circular Layout)
    medallion_y = 1710
    medallion_size = 80
    medallions = ["char_barney.png", "char_burns.png", "selo_bode_cera.png", "char_bart.png", "trowel.png"]
    m_start_x = center_x - ((medallion_size + 25) * len(medallions)) // 2
    
    for m_idx, m_file in enumerate(medallions):
        mx = m_start_x + m_idx * (medallion_size + 25)
        my = medallion_y
        
        # Desenha egrégora circular
        draw_p2.ellipse([mx, my, mx+medallion_size, my+medallion_size], fill=(235, 222, 192, 180), outline=(139, 90, 43, 200), width=2)
        
        m_path = BRANDING_DIR / m_file
        if m_path.exists():
            try:
                m_img = Image.open(m_path).convert("RGBA")
                m_img = m_img.resize((medallion_size-10, medallion_size-10), Image.Resampling.LANCZOS)
                p2.alpha_composite(m_img, (mx+5, my+5))
            except:
                pass
                
    # 5. Publicidade Discreta / Patrocinadores (1 logo horizontal ou texto)
    sponsor_logo_path = BRANDING_DIR / "sponsor_sindoficios.png"
    if sponsor_logo_path.exists():
        try:
            sp_img = Image.open(sponsor_logo_path).convert("RGBA")
            sp_w = 260
            sp_ratio = sp_w / sp_img.size[0]
            sp_h = int(sp_img.size[1] * sp_ratio)
            sp_img = sp_img.resize((sp_w, sp_h), Image.Resampling.LANCZOS)
            
            px = center_x - sp_w // 2
            py = 1800
            p2.alpha_composite(sp_img, (px, py))
        except:
            _draw_centered(draw_p2, "Apoio Institucional: Sind Ofícios - www.sindoficios.com.br", center_x, 1810, font_meta, (120, 100, 80, 200))
    else:
        _draw_centered(draw_p2, "Apoio Institucional: Sind Ofícios - www.sindoficios.com.br", center_x, 1815, font_meta, (120, 100, 80, 200))
        
    # Salva arquivos temporários isolados
    temp_dir = tempfile.gettempdir()
    uid = membro.get("telegram_id", membro.get("Telegram ID", "anon"))
    
    out_p1 = os.path.join(temp_dir, f"bode_diploma_{uid}_p1.png")
    out_p2 = os.path.join(temp_dir, f"bode_diploma_{uid}_p2.png")
    
    p1.convert("RGB").save(out_p1, "PNG", optimize=True)
    p2.convert("RGB").save(out_p2, "PNG", optimize=True)
    
    logger.info("Diploma carrossel 2 páginas renderizado com sucesso.")
    return [out_p1, out_p2]
