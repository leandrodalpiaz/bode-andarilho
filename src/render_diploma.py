# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

# Diretórios de assets
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BRANDING_DIR = ASSETS_DIR / "branding"

DEFAULT_TEXT_COLOR = (58, 36, 16, 255)  # Castanho envelhecido elegante
GOLD_TEXT_COLOR = (235, 195, 100, 230)   # Dourado queimado para lacres de cera

CONQUISTAS_MONOGRAMAS = {
    "ic": {"sigla": "IC", "nome": "Iniciado na Colher"},
    "mp": {"sigla": "MP", "nome": "Mestre de Marca"},
    "e9": {"sigla": "E9", "nome": "Eleito dos Nove"},
    "ce": {"sigla": "CE", "nome": "Cavaleiro da Estrada"},
    "og": {"sigla": "OG", "nome": "Cavaleiro do Garfo"},
    "pj": {"sigla": "PJ", "nome": "Príncipe Jerusalém"},
    "rc": {"sigla": "RC", "nome": "Rosa-Cruz de Visitas"},
    "na": {"sigla": "NA", "nome": "Noaquita Asfalto"},
    "rs": {"sigla": "RS", "nome": "Real Segredo"},
    "io": {"sigla": "IO", "nome": "Intendente Oficina"},
    "pm": {"sigla": "PM", "nome": "Mestre Passado"},
}


def _load_custom_font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Tenta carregar fonte do diretório assets, senão usa fallback."""
    path = FONTS_DIR / name
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            pass
    # Fallback sistêmico
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


def renderizar_diploma(membro: Dict[str, Any], conquistas_obtidas: List[str]) -> str:
    """
    Gera o Diploma Digital do Obreiro em PNG e retorna o caminho do arquivo gerado.
    """
    bg_path = BRANDING_DIR / "diploma_pergaminho_bg.png"
    seal_base_path = BRANDING_DIR / "selo_cera_base.png"
    sig_path = BRANDING_DIR / "bode_andarilho_watermark.png"
    
    if not bg_path.exists():
        raise FileNotFoundError(f"Fundo do diploma não encontrado em {bg_path}")
        
    # Carrega o pergaminho de fundo
    diploma = Image.open(bg_path).convert("RGBA")
    width, height = diploma.size
    
    draw = ImageDraw.Draw(diploma)
    center_x = width // 2
    
    # 1. Carrega Fontes
    font_titulo = _load_custom_font("Cinzel-Regular.ttf", int(width * 0.048))
    font_subtitulo = _load_custom_font("Cinzel-Regular.ttf", int(width * 0.030))
    font_nome = _load_custom_font("CormorantGaramond-SemiBold.ttf", int(width * 0.070))
    font_corpo = _load_custom_font("CormorantGaramond-SemiBold.ttf", int(width * 0.036))
    font_metadado = _load_custom_font("CormorantGaramond-SemiBold.ttf", int(width * 0.030))
    font_selo = _load_custom_font("Cinzel-Regular.ttf", 24) # Fonte fixa relativa ao selo 300x300
    
    y_cursor = int(height * 0.14)
    
    # 2. Escreve o Cabeçalho e Título
    y_cursor = _draw_centered(draw, "EGRÉGORA DO BODE ANDARILHO", center_x, y_cursor, font_subtitulo, (110, 80, 50, 210)) + 10
    
    # Desenha uma linha decorativa sutil
    draw.line((center_x - int(width * 0.25), y_cursor, center_x + int(width * 0.25), y_cursor), fill=(110, 80, 50, 120), width=2)
    y_cursor += 40
    
    y_cursor = _draw_centered(draw, "DIPLOMA DE ANDARILHO", center_x, y_cursor, font_titulo, DEFAULT_TEXT_COLOR) + 30
    
    # 3. Proclamação
    proclamacao = (
        "Pelo presente ato, reconhecemos solenemente a caminhada exemplar "
        "deste valoroso Obreiro, que percorreu colunas e caminhos virtuais, "
        "estreitando laços de fraternidade e fortalecendo a cadeia de união."
    )
    y_cursor = _wrap_and_draw_centered(
        draw, proclamacao, center_x, y_cursor, 
        _load_custom_font("CormorantGaramond-SemiBold.ttf", int(width * 0.028)), 
        (90, 65, 40, 230), int(width * 0.68)
    ) + 40
    
    # 4. Nome do Obreiro
    nome = str(membro.get("Nome", membro.get("nome", "Ir.·. Obreiro"))).strip().upper()
    y_cursor = _draw_centered(draw, nome, center_x, y_cursor, font_nome, DEFAULT_TEXT_COLOR) + 25
    
    # 5. Detalhes Maçônicos
    grau = str(membro.get("Grau", membro.get("grau", "Aprendiz"))).strip()
    loja = str(membro.get("Loja", membro.get("loja", "Loja não informada"))).strip()
    num_loja = str(membro.get("Número da loja", membro.get("numero_loja", ""))).strip()
    oriente = str(membro.get("Oriente", membro.get("oriente", ""))).strip()
    
    loja_texto = f"{loja}, nº {num_loja}" if num_loja and num_loja != "0" else loja
    
    meta_texto = f"Grau: {grau}  |  Oficina: {loja_texto}"
    if oriente:
        meta_texto += f"  |  Oriente: {oriente}"
        
    y_cursor = _draw_centered(draw, meta_texto, center_x, y_cursor, font_corpo, DEFAULT_TEXT_COLOR) + 80
    
    # 6. Seção de Conquistas (Os Selos de Cera)
    conquistas_filtradas = []
    for slug in conquistas_obtidas:
        slug = str(slug).strip().lower()
        if slug in CONQUISTAS_MONOGRAMAS:
            conquistas_filtradas.append(CONQUISTAS_MONOGRAMAS[slug])
            
    # Limita a 8 para manter harmonia visual, dispostas em grid de até 4x2
    conquistas_exibidas = conquistas_filtradas[:8]
    
    if conquistas_exibidas:
        y_cursor = _draw_centered(draw, "INSÍGNIAS E CONQUISTAS RECONHECIDAS", center_x, y_cursor, font_subtitulo, DEFAULT_TEXT_COLOR) + 25
        
        if seal_base_path.exists():
            seal_raw = Image.open(seal_base_path).convert("RGBA")
            
            # Define grid e espaçamentos
            # Grid dinâmico: determina colunas com base no total
            num_selos = len(conquistas_exibidas)
            cols = min(4, num_selos)
            
            # Escala o selo de cera: tamanho final no diploma
            target_seal_size = int(width * 0.12) # 12% da largura do diploma
            seal_base = seal_raw.resize((target_seal_size, target_seal_size), Image.Resampling.LANCZOS)
            
            # Gap horizontal entre os selos
            h_gap = int(width * 0.04)
            v_gap = int(height * 0.04)
            
            # Calcula a largura total de uma linha de selos para centralizar o bloco
            row_w = (target_seal_size * cols) + (h_gap * (cols - 1))
            start_x = center_x - (row_w // 2)
            
            # Prepara fonte do monograma na escala do selo
            monogram_font = _load_custom_font("Cinzel-Bold.ttf", int(target_seal_size * 0.34))
            label_font = _load_custom_font("CormorantGaramond-SemiBold.ttf", int(width * 0.020))
            
            for idx, info in enumerate(conquistas_exibidas):
                row = idx // cols
                col = idx % cols
                
                # Se for a última linha e tiver menos selos que o máximo, recalcula o start_x daquela linha específica
                if row == (num_selos - 1) // cols and (num_selos % cols) != 0:
                    resto = num_selos % cols
                    l_row_w = (target_seal_size * resto) + (h_gap * (resto - 1))
                    l_start_x = center_x - (l_row_w // 2)
                    sx = l_start_x + col * (target_seal_size + h_gap)
                else:
                    sx = start_x + col * (target_seal_size + h_gap)
                    
                sy = y_cursor + row * (target_seal_size + v_gap + 30)
                
                # Gera o selo individual com o monograma sobreposto
                selo_final = seal_base.copy()
                s_draw = ImageDraw.Draw(selo_final)
                
                # Escreve a sigla em dourado/branco escurecido bem no centro
                sigla = info["sigla"]
                sc_x = target_seal_size // 2
                sc_y = target_seal_size // 2 - 2
                
                # --- TIPOGRAFIA METÁLICA E RELEVO 3D EM OURO ---
                # Sombra profunda abaixo/direita para efeito fundido
                s_draw.text((sc_x+2, sc_y+2), sigla, font=monogram_font, fill=(30, 5, 5, 180), anchor="mm")
                # Brilho suave acima/esquerda (emboss)
                s_draw.text((sc_x-1, sc_y-1), sigla, font=monogram_font, fill=(255, 235, 180, 140), anchor="mm")
                # Texto Principal em Ouro Envelhecido Metálico
                s_draw.text((sc_x, sc_y), sigla, font=monogram_font, fill=GOLD_TEXT_COLOR, anchor="mm")
                
                # Aplica o selo no diploma usando composite
                diploma.alpha_composite(selo_final, (sx, sy))
                
                # Escreve o rótulo da medalha embaixo do selo
                lbl_x = sx + (target_seal_size // 2)
                lbl_y = sy + target_seal_size + 4
                
                # Escreve o título truncado ou formatado de forma elegante
                _draw_centered(draw, info["nome"], lbl_x, lbl_y, label_font, (70, 45, 20, 230))
                
            # Atualiza cursor para após o grid de selos
            linhas_grid = ((num_selos - 1) // cols) + 1
            y_cursor += linhas_grid * (target_seal_size + v_gap + 30) + 20
    else:
        # Caso não tenha medalhas, exibe incentivo fraternal
        y_cursor += 30
        _draw_centered(
            draw, 
            "Este obreiro iniciou recentemente sua jornada. Em breve novas medalhas ornarão seu diploma.", 
            center_x, y_cursor, 
            _load_custom_font("CormorantGaramond-SemiBold.ttf", int(width * 0.028)), 
            (130, 100, 80, 180)
        )
        y_cursor += 80
        
    # 7. Assinatura e Rodapé Final
    y_rodape = int(height * 0.82)
    
    if sig_path.exists():
        try:
            sig = Image.open(sig_path).convert("RGBA")
            # Redimensiona para parecer uma assinatura graciosa e sutil
            sig_w = int(width * 0.16)
            sig_ratio = sig_w / sig.size[0]
            sig_h = int(sig.size[1] * sig_ratio)
            sig = sig.resize((sig_w, sig_h), Image.Resampling.LANCZOS)
            
            # Ajusta a opacidade da assinatura para mesclar no papel
            alpha = sig.getchannel("A").point(lambda p: int(p * 0.35))
            sig.putalpha(alpha)
            
            # Coloca no centro abaixo
            sig_x = center_x - (sig_w // 2)
            diploma.alpha_composite(sig, (sig_x, y_rodape - 10))
        except Exception as es:
            logger.warning("Não consegui aplicar assinatura no diploma: %s", es)
            
    draw.line((center_x - int(width * 0.15), y_rodape + 15, center_x + int(width * 0.15), y_rodape + 15), fill=(110, 80, 50, 120), width=1)
    _draw_centered(draw, "Visto da Chancelaria", center_x, y_rodape + 20, font_metadado, (110, 80, 50, 210))
    
    # --- ESTETICA DO RIGOR: MARCA D'AGUA DIAGONAL PENDENTE ---
    status_aud = str(membro.get("status_auditoria") or membro.get("Status Auditoria") or "").strip()
    if status_aud == "Pendente_Identidade":
        try:
            stamp_layer = Image.new("RGBA", diploma.size, (255, 255, 255, 0))
            draw_stamp = ImageDraw.Draw(stamp_layer)
            
            stamp_text = "AGUARDANDO VALIDAÇÃO"
            font_stamp = _load_custom_font("Cinzel-Bold.ttf", int(width * 0.06))
            
            bbox = draw_stamp.textbbox((0, 0), stamp_text, font=font_stamp)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            
            tx = (width - tw) // 2
            ty = (height - th) // 2
            
            draw_stamp.text((tx, ty), stamp_text, font=font_stamp, fill=(180, 40, 40, 60))
            
            rotated_stamp = stamp_layer.rotate(30, resample=Image.Resampling.BICUBIC, center=(width//2, height//2))
            diploma.alpha_composite(rotated_stamp)
            logger.info("Marca d'agua de validacao pendente aplicada com sucesso.")
        except Exception as e_stamp:
            logger.warning("Erro ao aplicar marca d'agua estetica: %s", e_stamp)

    # Salva no diretório temporário de saída
    temp_dir = tempfile.gettempdir()
    uid = membro.get("telegram_id", membro.get("Telegram ID", "anon"))
    out_path = os.path.join(temp_dir, f"bode_diploma_{uid}.png")
    
    # Salva como RGB para remover o canal alfa final
    diploma.convert("RGB").save(out_path, "PNG", optimize=True)
    logger.info("Diploma digital renderizado com sucesso em: %s", out_path)
    
    return out_path
