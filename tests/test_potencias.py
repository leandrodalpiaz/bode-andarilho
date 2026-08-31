from src.potencias import (
    formatar_potencia,
    normalizar_potencia,
    potencia_requer_complemento,
    validar_potencia,
)


def test_potencia_legada_preserva_complemento_local():
    assert normalizar_potencia("GLMERGS") == ("CMSB", "GLMERGS")
    assert formatar_potencia("CMSB", "GLMERGS") == "GLMERGS"


def test_potencia_principal_exige_complemento():
    assert potencia_requer_complemento("GOB")
    assert not validar_potencia("GOB")
    assert validar_potencia("GOB", "GOB-RS")
