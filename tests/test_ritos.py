from src.ritos import RITOS_OFICIAIS, normalizar_rito, validar_rito


def test_rito_legado_eh_normalizado_para_valor_canonico():
    assert normalizar_rito("Rito Escocês Antigo e Aceito") == "REAA"
    assert normalizar_rito("rito de york") == "York"


def test_rito_desconhecido_nao_eh_aceito():
    assert normalizar_rito("Rito inventado") == ""
    assert not validar_rito("Rito inventado")
    assert all(valor for valor in RITOS_OFICIAIS)
