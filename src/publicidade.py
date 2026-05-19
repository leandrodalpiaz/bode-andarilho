# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BRANDING_DIR = ASSETS_DIR / "branding"


def obter_publicidade_diploma() -> dict:
    """Retorna a publicidade visual usada no rodapé do diploma."""
    logo_path = BRANDING_DIR / "sponsor_sindoficios.png"
    if logo_path.exists():
        return {
            "nome": "Apoio Institucional",
            "mensagem": "Sind Ofícios apoia a jornada fraterna do Bode Andarilho.",
            "imagem": str(logo_path),
        }

    return {
        "nome": "Sua imagem aqui",
        "mensagem": "Você pode apoiar o Bode Andarilho deixando sua marca neste espaço.",
        "imagem": None,
    }
