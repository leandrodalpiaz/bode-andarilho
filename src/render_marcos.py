# -*- coding: utf-8 -*-
import os
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Assets Layout setup
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BRANDING_DIR = ASSETS_DIR / "branding"
POTENCIAS_DIR = ASSETS_DIR / "potencias"

DEFAULT_GOLD = (130, 100, 60, 255)
DARK_TEXT = (40, 25, 15, 255)
CRIMSON_RED = (140, 35, 35, 255)

def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONTS_DIR / name
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            pass
    # System Fallbacks
    for f in ["georgia.ttf", "Georgia.ttf", "times.ttf"]:
        try:
            return ImageFont.truetype(f, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

def _draw_centered_x(draw: ImageDraw.ImageDraw, text: str, cx: int, y: int, font: ImageFont.ImageFont, fill: Tuple[int, int, int, int]) -> int:
    draw.text((cx, y), text, font=font, fill=fill, anchor="ma")
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    h = bbox[3] - bbox[1]
    return y + h

def _wrap_text_centered(draw: ImageDraw.ImageDraw, text: str, cx: int, y: int, font: ImageFont.ImageFont, fill: Tuple[int, int, int, int], max_w: int) -> int:
    words = str(text).split()
    lines = []
    curr = []
    for w in words:
        cand = " ".join(curr + [w])
        bbox = draw.textbbox((0, 0), cand, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            curr.append(w)
        else:
            lines.append(" ".join(curr))
            curr = [w]
    if curr: lines.append(" ".join(curr))
    
    cy = y
    for line in lines:
        cy = _draw_centered_x(draw, line, cx, cy, font, fill) + 8
    return cy

def renderizar_card_celebracao(
    tipo_marco: str, 
    titulo: str, 
    subtitulo: str, 
    detalhes: str, 
    potencia: Optional[str] = None,
    monograma_selo: str = "EX"
) -> str:
    """
    Gera um card comemorativo 1200x675 combinando o fundo ornado,
    o brasão da potência, a tipografia em Cinzel-Bold e um selo de cera.
    """
    bg_path = BRANDING_DIR / "marco_celebracao_bg.png"
    # Fallback para o diploma caso o asset premium nao esteja carregado
    if not bg_path.exists():
        bg_path = BRANDING_DIR / "diploma_pergaminho_bg.png"
        
    try:
        # 1. Carrega canvas base
        canvas = Image.open(bg_path).convert("RGBA")
        canvas = canvas.resize((1200, 675), Image.Resampling.LANCZOS)
        width, height = canvas.size
        draw = ImageDraw.Draw(canvas)
        
        cx = width // 2
        
        # 2. Carrega Fontes
        font_titulo = _load_font("Cinzel-Bold.ttf", 48)
        font_sub = _load_font("Cinzel-Regular.ttf", 30)
        font_det = _load_font("CormorantGaramond-SemiBold.ttf", 34)
        font_footer = _load_font("CormorantGaramond-Italic.ttf", 26)
        
        # 3. Plotagem do Brasão da Potência (Esquerda)
        pot_filename = f"{str(potencia).strip().lower()}.png"
        pot_path = POTENCIAS_DIR / pot_filename
        
        if not pot_path.exists():
            # Fallback generic
            pot_path = POTENCIAS_DIR / "gob.png" if (POTENCIAS_DIR / "gob.png").exists() else None
            
        if pot_path and pot_path.exists():
            try:
                brasao = Image.open(pot_path).convert("RGBA")
                b_w = 220
                ratio = b_w / brasao.size[0]
                b_h = int(brasao.size[1] * ratio)
                brasao = brasao.resize((b_w, b_h), Image.Resampling.LANCZOS)
                
                # Adiciona suavidade alpha para mesclar no papel
                alpha = brasao.getchannel("A").point(lambda p: int(p * 0.85))
                brasao.putalpha(alpha)
                
                bx = 80
                by = (height - b_h) // 2
                canvas.alpha_composite(brasao, (bx, by))
            except Exception as eb:
                logger.warning("Falha ao compor brasao esquerdo no card: %s", eb)
                
        # 4. Plotagem do Selo de Cera (Direita)
        selo_path = BRANDING_DIR / "selo_cera_base.png"
        if selo_path.exists():
            try:
                selo = Image.open(selo_path).convert("RGBA")
                s_w = 200
                selo = selo.resize((s_w, s_w), Image.Resampling.LANCZOS)
                
                s_draw = ImageDraw.Draw(selo)
                font_monogram = _load_font("Cinzel-Bold.ttf", 72)
                
                sc_x = s_w // 2
                sc_y = s_w // 2 - 4
                
                # Emboss / Relevo dourado 3D
                s_draw.text((sc_x+2, sc_y+2), monograma_selo, font=font_monogram, fill=(30, 5, 5, 190), anchor="mm")
                s_draw.text((sc_x-1, sc_y-1), monograma_selo, font=font_monogram, fill=(255, 235, 180, 150), anchor="mm")
                s_draw.text((sc_x, sc_y), monograma_selo, font=font_monogram, fill=(235, 195, 100, 230), anchor="mm")
                
                sx = width - 80 - s_w
                sy = (height - s_w) // 2
                canvas.alpha_composite(selo, (sx, sy))
            except Exception as es:
                logger.warning("Falha ao compor selo direito no card: %s", es)
                
        # 5. Renderização de Textos Centrais
        centro_x = cx
        limite_w = 580 # Largura da coluna de texto centralizada
        
        y_cur = 150
        
        # Tipo de Marco (Header em Ouro)
        y_cur = _draw_centered_x(draw, tipo_marco.upper(), centro_x, y_cur, font_sub, DEFAULT_GOLD) + 15
        
        # Linha Decorativa
        draw.line((centro_x - 150, y_cur, centro_x + 150, y_cur), fill=(DEFAULT_GOLD[0], DEFAULT_GOLD[1], DEFAULT_GOLD[2], 120), width=2)
        y_cur += 40
        
        # Título do Acontecimento (Cinzel-Bold em Carmesim/Preto)
        y_cur = _wrap_text_centered(draw, titulo, centro_x, y_cur, font_titulo, CRIMSON_RED, limite_w) + 25
        
        # Subtítulo / Descrição elegante
        y_cur = _wrap_text_centered(draw, subtitulo, centro_x, y_cur, font_det, DARK_TEXT, limite_w) + 25
        
        # Rodapé da Mensagem
        y_cur = _wrap_text_centered(draw, detalhes, centro_x, y_cur, font_footer, (100, 75, 50, 230), limite_w)
        
        # 6. Salvamento do Arquivo Físico Temporário
        temp_dir = tempfile.gettempdir()
        import uuid
        out_name = f"bode_celebracao_{uuid.uuid4().hex[:8]}.png"
        out_path = os.path.join(temp_dir, out_name)
        
        canvas.convert("RGB").save(out_path, "PNG", optimize=True)
        logger.info("Card de Celebracao renderizado em: %s", out_path)
        
        return out_path
        
    except Exception as e:
        logger.error("Erro critico na geracao do card de celebracao: %s", e)
        raise e


def renderizar_relatorio_vigor(dados_vigor: Dict[str, Any]) -> str:
    """
    Gera o Card de Vigor da Oficina (1200x675) com 3 medalhões concêntricos:
    Agenda, Acolhimento e Engajamento, além de selos dinâmicos de premiação.
    """
    bg_path = BRANDING_DIR / "marco_celebracao_bg.png"
    if not bg_path.exists():
        bg_path = BRANDING_DIR / "diploma_pergaminho_bg.png"

    try:
        canvas = Image.open(bg_path).convert("RGBA")
        canvas = canvas.resize((1200, 675), Image.Resampling.LANCZOS)
        width, height = canvas.size
        draw = ImageDraw.Draw(canvas)

        cx = width // 2

        # 1. Fontes
        font_titulo_hud = _load_font("Cinzel-Regular.ttf", 28)
        font_loja = _load_font("Cinzel-Bold.ttf", 44)
        font_periodo = _load_font("CormorantGaramond-Italic.ttf", 24)
        font_val = _load_font("Cinzel-Bold.ttf", 38)
        font_lbl = _load_font("CormorantGaramond-SemiBold.ttf", 18)
        font_selo_desc = _load_font("CormorantGaramond-BoldItalic.ttf", 20)

        # 2. Cabeçalho
        # Título do Relatório
        y_cur = 120
        y_cur = _draw_centered_x(draw, "RELATÓRIO MENSAL DE VIGOR", cx, y_cur, font_titulo_hud, DEFAULT_GOLD) + 10
        
        # Linha Fina
        draw.line((cx - 200, y_cur, cx + 200, y_cur), fill=(DEFAULT_GOLD[0], DEFAULT_GOLD[1], DEFAULT_GOLD[2], 150), width=2)
        y_cur += 25

        # Nome da Oficina
        nome_loja = str(dados_vigor.get("nome_loja") or "Oficina").upper()
        num_loja = str(dados_vigor.get("numero_loja") or "")
        titulo_loja = f"{nome_loja}"
        if num_loja:
            titulo_loja += f" Nº {num_loja}"
            
        y_cur = _wrap_text_centered(draw, titulo_loja, cx, y_cur, font_loja, CRIMSON_RED, 800) + 15

        # Período
        periodo_txt = f"Período: {dados_vigor.get('periodo_inicio')} a {dados_vigor.get('periodo_fim')}"
        y_cur = _draw_centered_x(draw, periodo_txt, cx, y_cur, font_periodo, (100, 80, 60, 255))

        # 3. Renderização dos 3 Medalhões Concêntricos (HUD)
        y_medallions = 420
        pos_x = [300, 600, 900]
        
        # Dados a serem exibidos
        vigor_agenda = dados_vigor.get("vigor_agenda", 0.0)
        acolhimento = dados_vigor.get("acolhimento", 0)
        engajamento = dados_vigor.get("engajamento", 0.0)
        
        med_data = [
            {
                "cx": pos_x[0], "cy": y_medallions, 
                "val": f"{vigor_agenda}d" if vigor_agenda > 0 else "0d", 
                "lbl": "AGENDA\nANTECEDÊNCIA"
            },
            {
                "cx": pos_x[1], "cy": y_medallions, 
                "val": f"{acolhimento}", 
                "lbl": "ACOLHIMENTO\nVISITANTES"
            },
            {
                "cx": pos_x[2], "cy": y_medallions, 
                "val": f"{engajamento}%", 
                "lbl": "ENGAJAMENTO\nQUÓRUM"
            }
        ]

        for m in med_data:
            mcx, mcy = m["cx"], m["cy"]
            r = 105
            # Círculo levemente preenchido
            draw.ellipse((mcx - r, mcy - r, mcx + r, mcy + r), fill=(255, 252, 245, 190), outline=DEFAULT_GOLD, width=3)
            # Círculo interno tracejado ou fino
            r2 = 95
            draw.ellipse((mcx - r2, mcy - r2, mcx + r2, mcy + r2), outline=(DEFAULT_GOLD[0], DEFAULT_GOLD[1], DEFAULT_GOLD[2], 80), width=1)
            
            # Valor
            draw.text((mcx, mcy - 15), m["val"], font=font_val, fill=CRIMSON_RED, anchor="mm")
            # Label
            _wrap_text_centered(draw, m["lbl"], mcx, mcy + 20, font_lbl, DARK_TEXT, 160)

        # 4. Outorga de Selos de Conquista Laterais (Dinâmicos)
        selo_path = BRANDING_DIR / "selo_cera_base.png"
        
        def _desenhar_selo_recompensa(sx: int, sy: int, sigla: str, legenda: str):
            if not selo_path.exists(): return
            try:
                s_img = Image.open(selo_path).convert("RGBA")
                s_size = 140
                s_img = s_img.resize((s_size, s_size), Image.Resampling.LANCZOS)
                s_draw = ImageDraw.Draw(s_img)
                
                font_mon = _load_font("Cinzel-Bold.ttf", 46)
                sc_x = s_size // 2
                sc_y = s_size // 2 - 3
                
                # Efeito relevo dourado 3D
                s_draw.text((sc_x+2, sc_y+2), sigla, font=font_mon, fill=(30, 5, 5, 180), anchor="mm")
                s_draw.text((sc_x-1, sc_y-1), sigla, font=font_mon, fill=(255, 235, 180, 150), anchor="mm")
                s_draw.text((sc_x, sc_y), sigla, font=font_mon, fill=(235, 195, 100, 220), anchor="mm")
                
                canvas.alpha_composite(s_img, (sx, sy))
                
                # Legenda descritiva em cima ou embaixo do selo
                _draw_centered_x(draw, legenda.upper(), sx + s_size//2, sy + s_size + 8, font_selo_desc, CRIMSON_RED)
            except Exception as err_s:
                logger.warning("Erro ao plotar selo de vigor: %s", err_s)

        # Selo Esquerdo: Oficina de Excelência (Agenda >= 15 dias)
        if vigor_agenda >= 15.0:
            _desenhar_selo_recompensa(60, 480, "OE", "Excelência")
            
        # Selo Direito: Farol da Região (Visitantes > 10)
        if acolhimento > 10:
            _desenhar_selo_recompensa(width - 60 - 140, 480, "FR", "Farol")

        # 5. Salvamento final
        temp_dir = tempfile.gettempdir()
        import uuid
        out_name = f"bode_vigor_{uuid.uuid4().hex[:8]}.png"
        out_path = os.path.join(temp_dir, out_name)
        
        canvas.convert("RGB").save(out_path, "PNG", optimize=True)
        logger.info("Card de Vigor renderizado em: %s", out_path)
        
        return out_path

    except Exception as e:
        logger.error("Erro critico na geracao do card de vigor: %s", e)
        raise e

