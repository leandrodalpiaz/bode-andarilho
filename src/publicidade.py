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
            "mensagem": "O Sind Ofícios apoia o desenvolvimento e a manutenção do Bode Andarilho.",
            "imagem": str(logo_path),
        }

    return {
        "nome": "Divulgue sua marca",
        "mensagem": "Apoie o Bode Andarilho e exiba sua marca neste espaço.",
        "imagem": None,
    }
