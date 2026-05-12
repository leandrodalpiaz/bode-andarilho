from __future__ import annotations

import json
import logging
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)


DEFAULT_TEXT_COLOR = "#2b1a0c"
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "templates" / "default_event_card.png"
DEFAULT_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
DEFAULT_STAMP_DIR = Path(__file__).resolve().parent.parent / "assets" / "stamps"
DEFAULT_POTENCIA_DIR = Path(__file__).resolve().parent.parent / "assets" / "potencias"
DEFAULT_BADGE_COLORS = {
    "grau": "#7b3f00",
    "rito": "#254f7a",
    "potencia": "#4f6f35",
}
TITLE_FONT_CANDIDATES = (
    "Cinzel-SemiBold.ttf",
    "Cinzel-Regular.ttf",
    "CormorantGaramond-SemiBold.ttf",
    "LibreBaskerville-Regular.ttf",
    "Georgia.ttf",
    "georgia.ttf",
)
BODY_FONT_CANDIDATES = (
    "CormorantGaramond-SemiBold.ttf",
    "LibreBaskerville-Regular.ttf",
    "Georgia.ttf",
    "georgia.ttf",
    "Times New Roman.ttf",
    "times.ttf",
)


@dataclass
class RenderResult:
    path: str
    warnings: List[str]


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _slug_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", _norm(value).lower())
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return "".join(ch if ch.isalnum() else "_" for ch in ascii_text).strip("_")


def _get_any(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


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


def _load_font(
    size: int,
    preferred: str = "",
    extra_candidates: Iterable[str] = (),
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        preferred,
        *[str(DEFAULT_FONT_DIR / name) for name in extra_candidates],
        *[str(DEFAULT_FONT_DIR / name) for name in BODY_FONT_CANDIDATES],
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
            font = ImageFont.truetype(candidate, size=size)
            if "SemiBold" in str(candidate) and hasattr(font, "set_variation_by_axes"):
                try:
                    font.set_variation_by_axes([600])
                except Exception:
                    pass
            return font
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


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
    min_size: int,
    preferred: str = "",
    extra_candidates: Iterable[str] = (),
) -> ImageFont.ImageFont:
    for size in range(start_size, min_size - 1, -2):
        font = _load_font(size, preferred, extra_candidates)
        if _measure(draw, text, font)[0] <= max_width:
            return font
    return _load_font(min_size, preferred, extra_candidates)


def _draw_text_shadow(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int, int],
    anchor: Optional[str] = None,
    shadow: Tuple[int, int, int, int] = (255, 247, 218, 170),
) -> None:
    x, y = xy
    for ox, oy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        draw.text((x + ox, y + oy), text, font=font, fill=shadow, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: Iterable[str],
    center_x: int,
    y: int,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int, int],
    line_gap: int,
) -> int:
    current_y = y
    for line in lines:
        _draw_text_shadow(draw, (center_x, current_y), line, font=font, fill=fill, anchor="ma")
        current_y += max(_measure(draw, "Ag", font)[1], getattr(font, "size", 20)) + line_gap
    return current_y


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


def _badge_items(
    evento: Dict[str, Any],
    include_grau: bool = True,
    include_potencia: bool = True,
) -> Iterable[Tuple[str, str]]:
    for keys, label in (
        (("Grau", "grau"), "GRAU"),
        (("Rito", "rito"), "RITO"),
        (("Potência", "PotÃªncia", "potencia"), "POTÊNCIA"),
    ):
        if label == "GRAU" and not include_grau:
            continue
        if label.startswith("POT") and not include_potencia:
            continue
        value = _norm(_get_any(evento, *keys))
        if value:
            yield label, value.upper()


def _event_visual_parts(evento: Dict[str, Any]) -> Dict[str, str]:
    numero = _norm(_get_any(evento, "Número da loja", "NÃºmero da loja", "numero_loja"))
    numero_fmt = f" {numero}" if numero and numero != "0" else ""
    loja = f"{_norm(_get_any(evento, 'Nome da loja', 'nome_loja'))}{numero_fmt}".strip()
    oriente_potencia = " - ".join(
        [
            v
            for v in (
                _norm(_get_any(evento, "Oriente", "oriente")),
                _norm(_get_any(evento, "Potência", "PotÃªncia", "potencia")),
            )
            if v
        ]
    )
    potencia = _norm(_get_any(evento, "Potência", "PotÃªncia", "potencia"))
    potencia_complemento = _norm(_get_any(evento, "Potência complemento", "PotÃªncia complemento", "potencia_complemento"))
    return {
        "titulo": _norm(_get_any(evento, "Título", "Titulo", "titulo")) or "NOVA SESSÃO",
        "data_hora": f"{_norm(_get_any(evento, 'Data do evento', 'data_evento', 'data'))} • {_norm(_get_any(evento, 'Hora', 'hora'))}".strip(" •"),
        "grau": _norm(_get_any(evento, "Grau", "grau")),
        "loja": loja or "Loja",
        "oriente_potencia": oriente_potencia,
        "potencia": potencia,
        "potencia_complemento": potencia_complemento,
        "tipo": _norm(_get_any(evento, "Tipo de sessão", "Tipo de sessÃ£o", "tipo_sessao", "tipo_evento")),
        "rito": _norm(_get_any(evento, "Rito", "rito")),
        "traje": _norm(_get_any(evento, "Traje obrigatório", "Traje obrigatÃ³rio", "traje_obrigatorio")),
        "agape": _norm(_get_any(evento, "Ágape", "Ãgape", "agape")),
        "observacoes": _norm(_get_any(evento, "Observações", "ObservaÃ§Ãµes", "observacoes", "ordem_do_dia")),
    }


def _is_default_template_source(template: str, loja: Dict[str, Any]) -> bool:
    custom_template = _norm(_get_any(loja, "Template sessão URL", "Template sessÃ£o URL", "template_sessao_url"))
    if not custom_template:
        return True
    try:
        return Path(template).resolve() == DEFAULT_TEMPLATE_PATH.resolve()
    except Exception:
        return False


def _draw_badges_artistic(
    draw: ImageDraw.ImageDraw,
    evento: Dict[str, Any],
    loja: Dict[str, Any],
    x: int,
    y: int,
    max_width: int,
    font: ImageFont.ImageFont,
    include_grau: bool = True,
    include_potencia: bool = True,
) -> int:
    bx = x
    by = y
    max_y = y
    for label, value in _badge_items(evento, include_grau=include_grau, include_potencia=include_potencia):
        kind = "grau" if label == "GRAU" else "rito" if label == "RITO" else "potencia"
        color_keys = {
            "grau": ("Cor selo grau", "cor_selo_grau"),
            "rito": ("Cor selo rito", "cor_selo_rito"),
            "potencia": ("Cor selo potência", "Cor selo potÃªncia", "cor_selo_potencia"),
        }[kind]
        fill = _hex_to_rgba(_norm(_get_any(loja, *color_keys)) or DEFAULT_BADGE_COLORS[kind], 230)
        text = f"{label}: {value}"
        tw, th = _measure(draw, text, font)
        pad_x, pad_y = 16, 7
        badge_w = tw + pad_x * 2
        badge_h = th + pad_y * 2
        if bx + badge_w > x + max_width:
            bx = x
            by = max_y + 8
        draw.rounded_rectangle((bx, by, bx + badge_w, by + badge_h), radius=8, fill=fill)
        draw.text((bx + pad_x, by + pad_y), text, font=font, fill=(255, 248, 230, 255))
        max_y = max(max_y, by + badge_h)
        bx += badge_w + 10
    return max_y


def _degree_stamp_path(grau: str) -> Optional[Path]:
    slug = _slug_text(grau)
    if not slug:
        return None
    for key in ("aprendiz", "companheiro", "mestre"):
        if key in slug:
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate = DEFAULT_STAMP_DIR / f"{key}{ext}"
                if candidate.exists():
                    return candidate
    return None


def _potencia_stamp_path(potencia: str) -> Optional[Path]:
    slug = _slug_text(potencia)
    if not slug:
        return None
    for key in ("gob", "cmsb", "comab"):
        if slug == key:
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate = DEFAULT_POTENCIA_DIR / f"{key}{ext}"
                if candidate.exists():
                    return candidate
    return None


def _transparent_light_background(stamp: Image.Image) -> Image.Image:
    stamp = stamp.convert("RGBA")
    pixels = stamp.load()
    width, height = stamp.size
    for py in range(height):
        for px in range(width):
            r, g, b, a = pixels[px, py]
            if a and r > 242 and g > 242 and b > 242:
                pixels[px, py] = (r, g, b, 0)
    return stamp


def _apply_circular_mask(stamp: Image.Image) -> Image.Image:
    stamp = stamp.convert("RGBA")
    width, height = stamp.size
    size = min(width, height)
    left = max(0, (width - size) // 2)
    top = max(0, (height - size) // 2)
    stamp = stamp.crop((left, top, left + size, top + size))
    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    inset = max(2, size // 80)
    mdraw.ellipse((inset, inset, size - inset, size - inset), fill=255)
    alpha = stamp.getchannel("A")
    stamp.putalpha(ImageChops.multiply(alpha, mask))
    return stamp


def _remove_edge_background(stamp: Image.Image) -> Image.Image:
    stamp = stamp.convert("RGBA")
    pixels = stamp.load()
    width, height = stamp.size
    stack = []
    seen = set()
    for x in range(width):
        stack.append((x, 0))
        stack.append((x, height - 1))
    for y in range(height):
        stack.append((0, y))
        stack.append((width - 1, y))

    def is_background(px: int, py: int) -> bool:
        r, g, b, a = pixels[px, py]
        if a == 0:
            return True
        neutral = abs(r - g) <= 7 and abs(g - b) <= 7
        return neutral and r >= 185 and g >= 185 and b >= 185

    while stack:
        px, py = stack.pop()
        if px < 0 or py < 0 or px >= width or py >= height or (px, py) in seen:
            continue
        seen.add((px, py))
        if not is_background(px, py):
            continue
        r, g, b, _ = pixels[px, py]
        pixels[px, py] = (r, g, b, 0)
        stack.extend(((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)))
    return stamp


def _draw_degree_stamp(image: Image.Image, grau: str) -> bool:
    path = _degree_stamp_path(grau)
    if not path:
        return False
    try:
        stamp = ImageOps.exif_transpose(Image.open(path))
        stamp = _transparent_light_background(stamp)
        width, height = image.size
        target_w = int(width * 0.205)
        ratio = target_w / max(1, stamp.size[0])
        target_h = int(stamp.size[1] * ratio)
        stamp = stamp.resize((target_w, target_h), Image.Resampling.LANCZOS)
        stamp = stamp.rotate(-9, expand=True, resample=Image.Resampling.BICUBIC)

        alpha = stamp.getchannel("A").point(lambda p: int(p * 0.82))
        stamp.putalpha(alpha)

        x = width - stamp.size[0] - int(width * 0.105)
        y = int(height * 0.115)
        image.alpha_composite(stamp, (x, y))
        return True
    except Exception as exc:
        logger.warning("Falha ao aplicar selo de grau '%s': %s", grau, exc)
        return False


def _draw_potencia_stamp(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    potencia: str,
    complemento: str,
    font: ImageFont.ImageFont,
) -> bool:
    path = _potencia_stamp_path(potencia)
    if not path:
        return False
    try:
        stamp = ImageOps.exif_transpose(Image.open(path))
        stamp = _remove_edge_background(stamp)
        width, height = image.size
        target_w = int(width * 0.145)
        ratio = target_w / max(1, stamp.size[0])
        target_h = int(stamp.size[1] * ratio)
        stamp = stamp.resize((target_w, target_h), Image.Resampling.LANCZOS)
        alpha = stamp.getchannel("A").point(lambda p: int(p * 0.78))
        stamp.putalpha(alpha)

        x = int(width * 0.145)
        y = int(height * 0.095)
        image.alpha_composite(stamp, (x, y))
        if complemento:
            label = complemento.upper()
            tw, th = _measure(draw, label, font)
            pad_x, pad_y = 10, 5
            lx = x + max(0, (stamp.size[0] - tw - pad_x * 2) // 2)
            ly = y + stamp.size[1] + 3
            draw.rounded_rectangle(
                (lx, ly, lx + tw + pad_x * 2, ly + th + pad_y * 2),
                radius=8,
                fill=(43, 26, 12, 190),
            )
            draw.text((lx + pad_x, ly + pad_y), label, font=font, fill=(255, 248, 230, 255))
        return True
    except Exception as exc:
        logger.warning("Falha ao aplicar selo de potencia '%s': %s", potencia, exc)
        return False


def _render_default_template_card(
    image: Image.Image,
    evento: Dict[str, Any],
    loja: Dict[str, Any],
    output_dir: Optional[str],
) -> RenderResult:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    warnings: List[str] = []
    preferred_font = _norm(_get_any(loja, "Fonte padrão", "Fonte padrÃ£o", "fonte_padrao"))
    ink = _hex_to_rgba(_norm(_get_any(loja, "Cor texto padrão", "Cor texto padrÃ£o", "cor_texto_padrao")) or DEFAULT_TEXT_COLOR, 255)
    soft_ink = _hex_to_rgba("#3a2410", 245)
    parts = _event_visual_parts(evento)
    stamp_applied = _draw_degree_stamp(image, parts["grau"])

    margin_x = int(width * 0.145)
    top_y = int(height * 0.205)
    content_w = width - margin_x * 2
    center_x = width // 2

    badge_font = _load_font(max(18, width // 54), preferred_font, TITLE_FONT_CANDIDATES)
    potencia_stamp_applied = _draw_potencia_stamp(
        image,
        draw,
        parts["potencia"],
        parts["potencia_complemento"],
        _load_font(max(14, width // 68), preferred_font, TITLE_FONT_CANDIDATES),
    )
    badges_bottom = _draw_badges_artistic(
        draw,
        evento,
        loja,
        margin_x,
        top_y + (int(height * 0.04) if potencia_stamp_applied else 0),
        int(content_w * 0.46) if potencia_stamp_applied else content_w,
        badge_font,
        include_grau=not stamp_applied,
        include_potencia=not potencia_stamp_applied,
    )
    y = badges_bottom + int(height * 0.055)

    title_font = _load_font(max(28, width // 30), preferred_font, TITLE_FONT_CANDIDATES)
    loja_font = _fit_font(draw, parts["loja"], int(content_w * 0.92), max(46, width // 15), max(30, width // 28), preferred_font, TITLE_FONT_CANDIDATES)
    date_font = _load_font(max(30, width // 27), preferred_font, BODY_FONT_CANDIDATES)
    body_font = _load_font(max(27, width // 33), preferred_font, BODY_FONT_CANDIDATES)
    section_font = _load_font(max(28, width // 31), preferred_font, TITLE_FONT_CANDIDATES)
    note_font = _load_font(max(26, width // 35), preferred_font, BODY_FONT_CANDIDATES)

    _draw_text_shadow(draw, (center_x, y), parts["titulo"].upper(), title_font, ink, anchor="ma")
    y += int(height * 0.048)

    loja_lines = _wrap_text(draw, parts["loja"], loja_font, int(content_w * 0.94))
    if len(loja_lines) > 2:
        loja_font = _fit_font(draw, parts["loja"], int(content_w * 0.94), max(34, width // 22), max(24, width // 38), preferred_font, TITLE_FONT_CANDIDATES)
        loja_lines = _wrap_text(draw, parts["loja"], loja_font, int(content_w * 0.94))[:2]
        warnings.append("Nome da Loja longo; card renderizado em tamanho reduzido.")
    y = _draw_centered_lines(draw, loja_lines, center_x, y, loja_font, ink, max(8, height // 135))
    if parts["oriente_potencia"]:
        y = _draw_centered_lines(draw, _wrap_text(draw, parts["oriente_potencia"], body_font, content_w), center_x, y + 2, body_font, soft_ink, 6)

    y += int(height * 0.032)
    if parts["data_hora"]:
        _draw_text_shadow(draw, (center_x, y), parts["data_hora"], date_font, ink, anchor="ma")
        y += int(height * 0.045)
    if parts["grau"]:
        _draw_text_shadow(draw, (center_x, y), f"Grau: {parts['grau']}", body_font, soft_ink, anchor="ma")
        y += int(height * 0.04)

    y += int(height * 0.025)
    _draw_text_shadow(draw, (center_x, y), "SESSÃO", section_font, ink, anchor="ma")
    y += int(height * 0.042)

    detail_lines = [
        f"Tipo: {parts['tipo']}" if parts["tipo"] else "",
        f"Rito: {parts['rito']}" if parts["rito"] else "",
        f"Traje: {parts['traje']}" if parts["traje"] else "",
        f"Ágape: {parts['agape']}" if parts["agape"] else "",
    ]
    for line in [line for line in detail_lines if line]:
        y = _draw_centered_lines(draw, _wrap_text(draw, line, body_font, content_w), center_x, y, body_font, ink, 5)

    if parts["observacoes"]:
        y += int(height * 0.04)
        _draw_text_shadow(draw, (center_x, y), "ORDEM DO DIA", section_font, ink, anchor="ma")
        y += int(height * 0.043)
        max_note_bottom = int(height * 0.75)
        note_lines = _wrap_text(draw, parts["observacoes"], note_font, int(content_w * 0.88))
        line_h = max(_measure(draw, "Ag", note_font)[1], getattr(note_font, "size", 24)) + 6
        max_lines = max(1, (max_note_bottom - y) // line_h)
        if len(note_lines) > max_lines:
            note_lines = note_lines[:max_lines]
            note_lines[-1] = note_lines[-1].rstrip(" .") + "..."
            warnings.append("Ordem do dia longa; card renderizado com corte.")
        _draw_centered_lines(draw, note_lines, center_x, y, note_font, ink, 6)

    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    event_id = _norm(_get_any(evento, "ID Evento", "id_evento", "id") or "preview") or "preview"
    out_path = os.path.join(out_dir, f"bode_event_card_{event_id}.png")
    image.convert("RGB").save(out_path, "PNG", optimize=True)
    return RenderResult(path=out_path, warnings=warnings)


def render_event_card(evento: Dict[str, Any], loja: Dict[str, Any], output_dir: Optional[str] = None) -> RenderResult:
    template = _norm(loja.get("Template sessão URL") or loja.get("template_sessao_url"))
    if not template:
        if DEFAULT_TEMPLATE_PATH.exists():
            template = str(DEFAULT_TEMPLATE_PATH)
        else:
            raise ValueError(f"Template visual padrão não encontrado em {DEFAULT_TEMPLATE_PATH}.")

    image = ImageOps.exif_transpose(_open_image(template)).convert("RGBA")
    if _is_default_template_source(template, loja):
        return _render_default_template_card(image, evento, loja, output_dir)

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
