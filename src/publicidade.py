# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BRANDING_DIR = ASSETS_DIR / "branding"


def obter_publicidade_diploma() -> dict:
    """Retorna a publicidade visual usada no rodapé do diploma."""
    try:
        from src.apoio import TIPO_RODAPE_DIPLOMA, selecionar_criativo_apoio

        criativo = selecionar_criativo_apoio(TIPO_RODAPE_DIPLOMA)
        if criativo:
            return {
                "nome": criativo.get("titulo") or criativo.get("nome") or "Apoio Institucional",
                "mensagem": criativo.get("texto") or criativo.get("texto_curto") or "Apoio institucional ao Bode Andarilho.",
                "imagem": criativo.get("imagem_url") or criativo.get("logo_url") or None,
            }
    except Exception:
        pass

    logo_path = BRANDING_DIR / "sponsor_imobiliaria33.png"
    if logo_path.exists():
        return {
            "nome": "Imobiliária Trinta e Três",
            "mensagem": "Encontre o imóvel perfeito com a confiança, transparência e retidão que a sua família merece.",
            "imagem": str(logo_path),
        }

    return {
        "nome": "A sua marca vista por centenas de Irmãos",
        "mensagem": "Assim como você leu esta mensagem, a nossa comunidade leria sobre o seu negócio. Seja uma Coluna de Sustentação do projeto.",
        "imagem": None,
    }
