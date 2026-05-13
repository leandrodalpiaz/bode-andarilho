from __future__ import annotations

import unicodedata
from typing import Any


# Lista oficial enxuta (UX): valores canônicos gravados no banco.
RITOS_OFICIAIS = (
    "REAA",
    "York",
    "Emulação",
    "Moderno",
    "Brasileiro",
    "Adonhiramita",
    "Schröder",
)


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _slug(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", _norm(value).lower())
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    # mantém só letras/números/espaço, colapsa espaços
    out = "".join(ch if ch.isalnum() else " " for ch in ascii_text)
    return " ".join(out.split())


def normalizar_rito(value: Any) -> str:
    """
    Normaliza ritos legados/teste para um valor canônico.

    Objetivo: a partir de agora os registros passam a ser oficiais; portanto:
    - valores reconhecidos viram um dos RITOS_OFICIAIS
    - valores desconhecidos retornam string vazia (para forçar correção no fluxo)
    """
    raw = _norm(value)
    if not raw or raw.lower() == "nan":
        return ""

    slug = _slug(raw)

    aliases = {
        # REAA
        "reaa": "REAA",
        "rito escoces antigo e aceito": "REAA",
        "rito escoc s antigo e aceito": "REAA",
        "rito escoces antigo aceito": "REAA",
        "escoces antigo e aceito": "REAA",
        "escoces antigo aceito": "REAA",
        "escoces": "REAA",
        # York
        "york": "York",
        "rito de york": "York",
        # Emulação
        "emulacao": "Emulação",
        "emulação": "Emulação",
        "rito emulacao": "Emulação",
        "rito emulação": "Emulação",
        "emulation": "Emulação",
        # Moderno/Francês
        "moderno": "Moderno",
        "rito moderno": "Moderno",
        "frances": "Moderno",
        "francês": "Moderno",
        "rito frances": "Moderno",
        "rito francês": "Moderno",
        # Brasileiro
        "brasileiro": "Brasileiro",
        "rito brasileiro": "Brasileiro",
        # Adonhiramita
        "adonhiramita": "Adonhiramita",
        "rito adonhiramita": "Adonhiramita",
        # Schroder
        "schroder": "Schröder",
        "schröder": "Schröder",
        "rito schroder": "Schröder",
        "rito schröder": "Schröder",
    }

    mapped = aliases.get(slug)
    if mapped:
        return mapped

    # heurísticas simples
    if "reaa" in slug or "escoces" in slug:
        return "REAA"
    if "york" in slug:
        return "York"
    if "emul" in slug:
        return "Emulação"
    if "adon" in slug:
        return "Adonhiramita"
    if "brasil" in slug:
        return "Brasileiro"
    if "moderno" in slug or "frances" in slug:
        return "Moderno"
    if "schrod" in slug:
        return "Schröder"

    return ""


def validar_rito(value: Any) -> bool:
    return normalizar_rito(value) in RITOS_OFICIAIS

