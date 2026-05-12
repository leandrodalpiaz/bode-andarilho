from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)


DEFAULT_TEXT_COLOR = "#2b1a0c"
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "templates" / "default_event_card.png"
DEFAULT_BADGE_COLORS = {
    "grau": "#7b3f00",
    "rito": "#254f7a",
    "potencia": "#4f6f35",
}


@dataclass
class RenderResult:
    path: str
    warnings: List[str]


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _hex_to_rgba(value: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    raw = _norm(value) or DEFAULT_TEXT_COLOR
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), alpha)
    except Exception:
        return (43, 26, 12, alpha)


def _load_font(size: int, preferred: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        preferred,
        "georgia.ttf",
        "Georgia.ttf",
        "times.ttf",
        "Times New Roman.ttf",
        "DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "arial.ttf",
        "Arial.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    lines: List[str] = []
    for paragraph in str(text or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _measure(draw, candidate, font)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _open_image(source: str) -> Image.Image:
    if source.startswith(("http://", "https://")):
        resp = requests.get(source, timeout=20)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content)).convert("RGBA")
    return Image.open(source).convert("RGBA")


def _layout_config(loja: Dict[str, Any], width: int, height: int) -> Dict[str, Any]:
    raw = _norm(loja.get("Layout config JSON") or loja.get("layout_config_json"))
    data: Dict[str, Any] = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning("layout_config_json invalido para loja %s", loja.get("ID") or loja.get("id"))

    area = data.get("area_texto") if isinstance(data.get("area_texto"), dict) else data
    if not isinstance(area, dict):
        area = {}

    using_default_template = not _norm(loja.get("Template sessão URL") or loja.get("template_sessao_url"))
    margin_x = int(width * 0.15) if using_default_template else int(width * 0.12)
    margin_top = int(height * 0.18) if using_default_template else int(height * 0.24)
    margin_bottom = int(height * 0.24) if using_default_template else int(height * 0.12)
    return {
        "x": int(area.get("x", margin_x)),
        "y": int(area.get("y", margin_top)),
        "w": int(area.get("w", width - margin_x * 2)),
        "h": int(area.get("h", height - margin_top - margin_bottom)),
        "alinhamento": _norm(area.get("alinhamento") or "center").lower(),
        "cor_texto": _norm(area.get("cor_texto") or loja.get("Cor texto padrão") or DEFAULT_TEXT_COLOR),
        "fundo_translucido": bool(area.get("fundo_translucido", True)),
    }


def _event_text(evento: Dict[str, Any]) -> str:
    numero = _norm(evento.get("Número da loja"))
    numero_fmt = f" {numero}" if numero and numero != "0" else ""
    data_hora = f"{_norm(evento.get('Data do evento'))} - {_norm(evento.get('Hora'))}".strip(" -")
    loja = f"{_norm(evento.get('Nome da loja'))}{numero_fmt}".strip()
    oriente_potencia = " - ".join([v for v in (_norm(evento.get("Oriente")), _norm(evento.get("Potência"))) if v])
    linhas = [
        "NOVA SESSÃO",
        data_hora,
        f"Grau: {_norm(evento.get('Grau'))}" if _norm(evento.get("Grau")) else "",
        "",
        "LOJA",
        loja,
        oriente_potencia,
        "",
        "SESSÃO",
        f"Tipo: {_norm(evento.get('Tipo de sessão'))}" if _norm(evento.get("Tipo de sessão")) else "",
        f"Rito: {_norm(evento.get('Rito'))}" if _norm(evento.get("Rito")) else "",
        f"Traje: {_norm(evento.get('Traje obrigatório'))}" if _norm(evento.get("Traje obrigatório")) else "",
        f"Ágape: {_norm(evento.get('Ágape'))}" if _norm(evento.get("Ágape")) else "",
        "",
        "ORDEM DO DIA",
        _norm(evento.get("Observações")),
    ]
    out: List[str] = []
    for line in linhas:
        if line == "":
            if out and out[-1] != "":
                out.append("")
            continue
        if line:
            out.append(line)
    return "\n".join(out)


def _badge_items(evento: Dict[str, Any]) -> Iterable[Tuple[str, str]]:
    for key, label in (("Grau", "GRAU"), ("Rito", "RITO"), ("Potência", "POTÊNCIA")):
        value = _norm(evento.get(key))
        if value:
            yield label, value.upper()


def render_event_card(evento: Dict[str, Any], loja: Dict[str, Any], output_dir: Optional[str] = None) -> RenderResult:
    template = _norm(loja.get("Template sessão URL") or loja.get("template_sessao_url"))
    if not template:
        if DEFAULT_TEMPLATE_PATH.exists():
            template = str(DEFAULT_TEMPLATE_PATH)
        else:
            raise ValueError(f"Template visual padrão não encontrado em {DEFAULT_TEMPLATE_PATH}.")

    image = ImageOps.exif_transpose(_open_image(template)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    layout = _layout_config(loja, width, height)
    warnings: List[str] = []

    x, y, w, h = layout["x"], layout["y"], layout["w"], layout["h"]
    if layout["fundo_translucido"]:
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rounded_rectangle((x, y, x + w, y + h), radius=max(12, width // 90), fill=(255, 255, 255, 172))
        image = Image.alpha_composite(image, overlay)
        draw = ImageDraw.Draw(image)

    badge_font = _load_font(max(20, width // 48), _norm(loja.get("Fonte padrão") or loja.get("fonte_padrao")))
    bx = x
    by = max(20, y - max(46, height // 22))
    for idx, (label, value) in enumerate(_badge_items(evento)):
        kind = ("grau", "rito", "potencia")[min(idx, 2)]
        color_key = {
            "grau": "Cor selo grau",
            "rito": "Cor selo rito",
            "potencia": "Cor selo potência",
        }[kind]
        fill = _hex_to_rgba(_norm(loja.get(color_key)) or DEFAULT_BADGE_COLORS[kind], 235)
        text = f"{label}: {value}"
        tw, th = _measure(draw, text, badge_font)
        pad_x, pad_y = 14, 8
        if bx + tw + pad_x * 2 > x + w:
            bx = x
            by += th + pad_y * 3
        draw.rounded_rectangle((bx, by, bx + tw + pad_x * 2, by + th + pad_y * 2), radius=10, fill=fill)
        draw.text((bx + pad_x, by + pad_y), text, font=badge_font, fill=(255, 255, 255, 255))
        bx += tw + pad_x * 2 + 10

    text = _event_text(evento)
    preferred_font = _norm(loja.get("Fonte padrão") or loja.get("fonte_padrao"))
    font_size = max(24, width // 28)
    text_color = _hex_to_rgba(layout["cor_texto"], 255)
    line_spacing = max(8, height // 120)
    final_lines: List[str] = []
    final_font = _load_font(font_size, preferred_font)

    while font_size >= max(18, width // 52):
        font = _load_font(font_size, preferred_font)
        lines = _wrap_text(draw, text, font, w - 32)
        line_h = max(_measure(draw, "Ag", font)[1], font_size) + line_spacing
        if len(lines) * line_h <= h - 32:
            final_font = font
            final_lines = lines
            break
        font_size -= 2
    else:
        final_font = _load_font(font_size, preferred_font)
        final_lines = _wrap_text(draw, text, final_font, w - 32)
        max_lines = max(1, (h - 32) // (font_size + line_spacing))
        final_lines = final_lines[:max_lines]
        if final_lines:
            final_lines[-1] = final_lines[-1].rstrip(" .") + "..."
        warnings.append("Texto longo demais; card renderizado com corte.")

    line_h = max(_measure(draw, "Ag", final_font)[1], font_size) + line_spacing
    total_h = len(final_lines) * line_h
    ty = y + max(16, (h - total_h) // 2)
    for line in final_lines:
        tw, _ = _measure(draw, line, final_font)
        if layout["alinhamento"] == "left":
            tx = x + 24
        elif layout["alinhamento"] == "right":
            tx = x + w - tw - 24
        else:
            tx = x + max(24, (w - tw) // 2)
        draw.text((tx, ty), line, font=final_font, fill=text_color)
        ty += line_h

    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    event_id = _norm(evento.get("ID Evento") or evento.get("id_evento") or "preview") or "preview"
    out_path = os.path.join(out_dir, f"bode_event_card_{event_id}.png")
    image.convert("RGB").save(out_path, "PNG", optimize=True)
    return RenderResult(path=out_path, warnings=warnings)
