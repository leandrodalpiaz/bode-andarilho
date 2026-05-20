# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BRANDING_DIR = ASSETS_DIR / "branding"

WIDTH = 1080
HEIGHT = 1920
TEXT_DARK = (57, 35, 16, 255)
TEXT_MUTED = (92, 69, 45, 230)
GOLD = (202, 151, 52, 255)
GOLD_SOFT = (210, 174, 88, 180)
PARCHMENT = (239, 220, 176, 188)
PARCHMENT_SOFT = (247, 232, 191, 120)
LINE = (126, 82, 35, 165)


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONTS_DIR / name
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception as exc:
            logger.warning("Falha ao carregar fonte %s: %s", name, exc)

    for fallback in (
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/seguisym.ttf",
        "Georgia.ttf",
        "georgia.ttf",
        "Times New Roman.ttf",
        "times.ttf",
    ):
        try:
            return ImageFont.truetype(fallback, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _fit_font(name: str, text: str, max_width: int, start_size: int, min_size: int = 20) -> ImageFont.ImageFont:
    probe = Image.new("RGBA", (10, 10))
    draw = ImageDraw.Draw(probe)
    for size in range(start_size, min_size - 1, -2):
        font = _load_font(name, size)
        if _text_size(draw, text, font)[0] <= max_width:
            return font
    return _load_font(name, min_size)


def _value(membro: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        raw = membro.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return default


def _draw_center(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font: ImageFont.ImageFont, fill=TEXT_DARK) -> None:
    draw.text((x, y), text, font=font, fill=fill, anchor="mm")


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = str(text).split()
    lines: List[str] = []
    current: List[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if not current or _text_size(draw, candidate, font)[0] <= max_width:
            current.append(word)
            continue
        lines.append(" ".join(current))
        current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _formatar_data_nasc(data_str: str) -> str:
    if not data_str:
        return "Nao informada"
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(data_str).strip(), fmt).strftime("%d/%m/%Y")
        except Exception:
            continue
    return str(data_str).strip()


def _draw_profile_line(
    draw: ImageDraw.ImageDraw,
    label: str,
    value: str,
    x: int,
    y: int,
    label_font: ImageFont.ImageFont,
    value_font: ImageFont.ImageFont,
    max_width: int,
) -> None:
    label_text = f"{label}:"
    draw.text((x, y), label_text, font=label_font, fill=(78, 55, 31, 210), anchor="la")
    label_w = _text_size(draw, label_text, label_font)[0]
    val = str(value or "Nao informado").strip()
    val_font = _fit_font("CormorantGaramond-SemiBold.ttf", val, max_width - label_w - 12, 23, 17)
    draw.text((x + label_w + 12, y), val, font=val_font, fill=(57, 35, 16, 230), anchor="la")


def _load_template(path: Path) -> Image.Image:
    if path.exists():
        return Image.open(path).convert("RGBA").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)

    logger.warning("Template %s nao encontrado. Usando fundo simples.", path)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (241, 222, 181, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([42, 42, WIDTH - 42, HEIGHT - 42], radius=24, outline=LINE, width=6)
    return image


def _draw_badge_card(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    icon: str,
    title: str,
    description: str,
    percent: int,
) -> None:
    x1, y1, x2, y2 = box
    percent = max(0, min(100, int(percent or 0)))
    alpha = 3 if percent <= 0 else min(255, 18 + int(percent * 2.37))
    complete = percent >= 100

    card_fill = (248, 232, 190, max(1, min(145, alpha - 12)))
    card_line = (128, 86, 39, max(2, min(165, alpha)))
    draw.rounded_rectangle([x1, y1, x2, y2], radius=18, fill=card_fill, outline=card_line, width=2)

    icon_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    icon_draw = ImageDraw.Draw(icon_layer)
    icon_font = _load_font("C:/Windows/Fonts/seguiemj.ttf", 34)
    icon_box = [x1 + 16, y1 + 20, x1 + 76, y1 + 80]
    icon_draw.ellipse(icon_box, fill=(251, 239, 201, max(1, alpha)), outline=(156, 112, 45, alpha))
    glyph_box = icon_draw.textbbox((0, 0), icon, font=icon_font)
    glyph_w = glyph_box[2] - glyph_box[0]
    glyph_h = glyph_box[3] - glyph_box[1]
    glyph_x = x1 + 46 - glyph_w / 2 - glyph_box[0]
    glyph_y = y1 + 50 - glyph_h / 2 - glyph_box[1]
    icon_draw.text((glyph_x, glyph_y), icon, font=icon_font, fill=(61, 44, 25, alpha))
    image.alpha_composite(icon_layer)

    title_font = _fit_font("Cinzel-Regular.ttf", title, x2 - x1 - 110, 19, 14)
    desc_font = _load_font("CormorantGaramond-SemiBold.ttf", 19)
    pct_font = _load_font("Cinzel-Regular.ttf", 15)

    title_color = (58, 36, 16, alpha)
    desc_color = (88, 65, 42, max(2, alpha - 18))
    draw.text((x1 + 92, y1 + 20), title, font=title_font, fill=title_color)

    for idx, line in enumerate(_wrap_lines(draw, description, desc_font, x2 - x1 - 112)[:2]):
        draw.text((x1 + 92, y1 + 48 + idx * 22), line, font=desc_font, fill=desc_color)

    bar_x = x1 + 92
    bar_y = y2 - 30
    bar_w = x2 - bar_x - 18
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 8], radius=4, fill=(130, 98, 55, max(1, min(84, alpha))))
    if percent:
        fill = GOLD if complete else (164, 122, 47, max(80, alpha))
        draw.rounded_rectangle([bar_x, bar_y, bar_x + int(bar_w * percent / 100), bar_y + 8], radius=4, fill=fill)

    label = "Conquista liberada" if complete else f"{percent}%"
    draw.text((bar_x + bar_w, bar_y - 18), label, font=pct_font, fill=(72, 48, 24, max(2, alpha)), anchor="ra")


def _draw_ad_slot(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    try:
        from src.publicidade import obter_publicidade_diploma

        ad = obter_publicidade_diploma()
    except Exception as exc:
        logger.warning("Falha ao obter publicidade do diploma: %s", exc)
        ad = {}

    x1, y1, x2, y2 = 170, 1668, 910, 1778
    draw.rounded_rectangle([x1, y1, x2, y2], radius=24, fill=(246, 231, 190, 116), outline=(139, 96, 42, 115), width=2)

    image_path = ad.get("imagem")
    if image_path and Path(str(image_path)).exists():
        try:
            logo = Image.open(str(image_path)).convert("RGBA")
            logo.thumbnail((170, 78), Image.Resampling.LANCZOS)
            image.alpha_composite(logo, (x1 + 24, y1 + (y2 - y1 - logo.height) // 2))
        except Exception as exc:
            logger.warning("Falha ao inserir imagem de publicidade: %s", exc)
            image_path = None

    title = ad.get("nome") or "Divulgue sua marca"
    message = ad.get("mensagem") or "Você pode apoiar o Bode Andarilho exibindo sua marca neste espaço."
    title_font = _load_font("Cinzel-Regular.ttf", 22)
    msg_font = _load_font("CormorantGaramond-SemiBold.ttf", 22)

    if image_path:
        text_x = x1 + 220
        max_w = x2 - text_x - 28
        anchor = "la"
    else:
        text_x = x1 + 214
        max_w = x2 - text_x - 28
        anchor = "la"
        draw.rounded_rectangle([x1 + 30, y1 + 25, x1 + 168, y2 - 25], radius=16, outline=(151, 107, 45, 105), width=2)
        mini_font = _load_font("Cinzel-Regular.ttf", 16)
        for line_idx, line in enumerate(("SUA", "IMAGEM", "AQUI")):
            _draw_center(draw, line, x1 + 99, y1 + 35 + line_idx * 19, mini_font, (83, 58, 31, 128))

    draw.text((text_x, y1 + 26), title, font=title_font, fill=(69, 47, 23, 190), anchor=anchor)
    y = y1 + 58
    for line in _wrap_lines(draw, message, msg_font, max_w)[:2]:
        draw.text((text_x, y), line, font=msg_font, fill=(88, 65, 40, 178), anchor=anchor)
        y += 24


def renderizar_diploma(membro: Dict[str, Any], conquistas_obtidas: List[str], progressos: Dict[str, int]) -> List[str]:
    p1 = _load_template(BRANDING_DIR / "diploma_vertical_p1.png")
    p2 = _load_template(BRANDING_DIR / "diploma_vertical_p2.png")

    draw_p1 = ImageDraw.Draw(p1)
    draw_p2 = ImageDraw.Draw(p2)
    center_x = WIDTH // 2

    nome = _value(membro, "Nome", "nome", default="Ir.·. Obreiro").upper()
    grau = _value(membro, "Grau", "grau", default="Aprendiz")
    loja = _value(membro, "Loja", "loja", default="Oficina nao informada")
    numero = _value(membro, "Número da loja", "Numero da loja", "numero_loja")
    oriente = _value(membro, "Oriente", "oriente", "Cidade", "cidade", default="Oriente nao informado")
    potencia = _value(membro, "Potência", "potencia", default="Nao informada")
    data_nasc = _formatar_data_nasc(_value(membro, "Data de nascimento", "data_nasc"))
    vm = _value(membro, "Venerável Mestre", "veneravel_mestre", "vm", default="Nao")
    mi = _value(membro, "Mestre Instalado", "mestre_instalado", "mi", default="Nao")
    nivel = str(_value(membro, "Nivel", "nivel", default="1"))
    nivel_texto = {"1": "Obreiro", "2": "Secretário", "3": "Administrador"}.get(nivel, "Obreiro")
    loja_texto = f"{loja}, nº {numero}" if numero and numero != "0" else loja

    # A capa real ja traz a identidade visual. Os dados entram no espaco livre inferior.
    name_font = _fit_font("CormorantGaramond-SemiBold.ttf", nome, 760, 62, 34)
    meta_font = _fit_font("CormorantGaramond-SemiBold.ttf", f"{grau} | {loja_texto}", 770, 30, 22)
    ori_font = _load_font("Cinzel-Regular.ttf", 22)
    label_font = _load_font("Cinzel-Regular.ttf", 18)
    value_font = _load_font("CormorantGaramond-SemiBold.ttf", 22)

    panel = Image.new("RGBA", p1.size, (255, 255, 255, 0))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle([126, 690, 954, 1088], radius=32, fill=(244, 224, 182, 86), outline=(121, 82, 34, 78), width=2)
    p1.alpha_composite(panel)
    _draw_center(draw_p1, nome, center_x, 740, name_font, TEXT_DARK)
    _draw_center(draw_p1, f"{grau} | {loja_texto}", center_x, 796, meta_font, TEXT_MUTED)
    _draw_center(draw_p1, f"Oriente de {oriente} - {datetime.now().year}", center_x, 838, ori_font, (73, 51, 28, 205))

    perfil_linhas = [
        ("Nascimento", data_nasc),
        ("Grau", grau),
        ("Loja", loja_texto),
        ("Oriente", oriente),
        ("Potência", potencia),
        ("Venerável Mestre", vm),
        ("Mestre Instalado", mi),
        ("Nível de acesso", nivel_texto),
    ]
    for idx, (label, value) in enumerate(perfil_linhas):
        _draw_profile_line(draw_p1, label, value, 180, 872 + idx * 27, label_font, value_font, 720)

    if _value(membro, "status_auditoria", "Status Auditoria") == "Pendente_Identidade":
        stamp = Image.new("RGBA", p1.size, (255, 255, 255, 0))
        stamp_draw = ImageDraw.Draw(stamp)
        stamp_draw.text((center_x, 1030), "AGUARDANDO VALIDACAO", font=_load_font("Cinzel-Regular.ttf", 56), fill=(160, 38, 36, 64), anchor="mm")
        p1.alpha_composite(stamp.rotate(28, resample=Image.Resampling.BICUBIC, center=(center_x, 1030)))

    title_font = _load_font("Cinzel-Regular.ttf", 42)
    subtitle_font = _load_font("CormorantGaramond-SemiBold.ttf", 27)
    _draw_center(draw_p2, "QUADRO DE CONQUISTAS", center_x, 250, title_font, TEXT_DARK)
    _draw_center(draw_p2, "Sua jornada cresce a cada presença, visita e marco registrado.", center_x, 298, subtitle_font, TEXT_MUTED)

    try:
        from src.conquistas import CONQUISTAS_INFO
    except Exception as exc:
        logger.warning("Falha ao importar CONQUISTAS_INFO: %s", exc)
        CONQUISTAS_INFO = {}

    obtained = {str(slug).strip().lower() for slug in (conquistas_obtidas or [])}
    items = list(CONQUISTAS_INFO.items())[:12]
    start_x = 110
    start_y = 375
    card_w = 405
    card_h = 128
    gap_x = 50
    gap_y = 26

    for idx, (slug, info) in enumerate(items):
        row = idx // 2
        col = idx % 2
        x1 = start_x + col * (card_w + gap_x)
        y1 = start_y + row * (card_h + gap_y)
        percent = int(progressos.get(slug, 0) or 0)
        if slug in obtained:
            percent = max(percent, 100)
        icon = str(info.get("emoji") or "★")
        icon = {
            "ce": "↗",
            "bv": "◆",
        }.get(slug, icon)
        _draw_badge_card(
            p2,
            draw_p2,
            (x1, y1, x1 + card_w, y1 + card_h),
            icon,
            str(info.get("titulo") or slug).strip(),
            str(info.get("descricao") or "").strip(),
            percent,
        )

    _draw_ad_slot(p2, draw_p2)

    temp_dir = tempfile.gettempdir()
    uid = _value(membro, "telegram_id", "Telegram ID", default="anon")
    out_p1 = os.path.join(temp_dir, f"bode_diploma_{uid}_p1.png")
    out_p2 = os.path.join(temp_dir, f"bode_diploma_{uid}_p2.png")
    p1.convert("RGB").save(out_p1, "PNG", optimize=True)
    p2.convert("RGB").save(out_p2, "PNG", optimize=True)

    logger.info("Diploma carrossel 2 paginas renderizado com sucesso.")
    return [out_p1, out_p2]
