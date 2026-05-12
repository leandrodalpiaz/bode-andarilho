from __future__ import annotations

import unicodedata
from typing import Any, Dict, Tuple


POTENCIAS_PRINCIPAIS = ("GOB", "CMSB", "COMAB")
POTENCIAS_COM_COMPLEMENTO = {"GOB", "CMSB", "COMAB"}


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _slug(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", _norm(value).upper())
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join("".join(ch if ch.isalnum() else " " for ch in ascii_text).split())


def normalizar_potencia(potencia: Any, complemento: Any = "") -> Tuple[str, str]:
    principal = _norm(potencia).upper()
    comp = _norm(complemento).upper()
    slug = _slug(principal)

    if principal in POTENCIAS_PRINCIPAIS:
        return principal, comp

    if slug.startswith("GOB"):
        return "GOB", comp or _norm(potencia).upper()

    grandes_lojas = {
        "GRANDE LOJA RS",
        "GRANDE LOJA R S",
        "GRANDE LOJA DO RIO GRANDE DO SUL",
        "GLMERGS",
        "GLESP",
    }
    if slug in grandes_lojas or slug.startswith("GL"):
        return "CMSB", comp or _norm(potencia).upper()

    grandes_orientes = {"GORGS", "GOSC", "GOP", "GOMG", "GOIAS", "GOPR"}
    if slug in grandes_orientes or slug.startswith("GO"):
        return "COMAB", comp or _norm(potencia).upper()

    return principal, comp


def potencia_requer_complemento(potencia: Any) -> bool:
    principal, _ = normalizar_potencia(potencia)
    return principal in POTENCIAS_COM_COMPLEMENTO


def validar_potencia(potencia: Any, complemento: Any = "") -> bool:
    principal, comp = normalizar_potencia(potencia, complemento)
    if principal not in POTENCIAS_PRINCIPAIS:
        return False
    return not potencia_requer_complemento(principal) or bool(comp)


def formatar_potencia(potencia: Any, complemento: Any = "") -> str:
    principal, comp = normalizar_potencia(potencia, complemento)
    if comp and principal in POTENCIAS_COM_COMPLEMENTO:
        return f"{principal} - {comp}"
    if comp and principal == "GOB":
        return f"{principal} - {comp}"
    return principal


def potencia_de_dados(dados: Dict[str, Any]) -> Tuple[str, str]:
    return normalizar_potencia(
        dados.get("Potência") or dados.get("PotÃªncia") or dados.get("potencia"),
        dados.get("Potência complemento")
        or dados.get("PotÃªncia complemento")
        or dados.get("potencia_complemento")
        or dados.get("potencia_outra"),
    )
