from src.adapters.cards import to_legacy_card_payload
from src.render_cards import render_event_card


def test_adapter_de_card_formata_fuso_e_nao_consulta_legado(tmp_path):
    event = {
        "id": 10,
        "evento_at": "2026-09-10T23:00:00+00:00",
        "titulo": "Sessão ordinária",
        "descricao": "Ordem do dia",
        "grau": "Mestre",
        "tipo_sessao": "Ordinária",
    }
    store = {
        "id": 7,
        "nome": "Loja Piloto",
        "numero_loja": "12",
        "cidade": "São Paulo",
        "uf": "SP",
        "rito": "REAA",
        "potencia": "GOB",
        "potencia_complemento": "SP",
        "layout_config": {},
    }

    legacy_event, legacy_store = to_legacy_card_payload(event, store)
    assert legacy_event["Data do evento"] == "10/09/2026"
    assert legacy_event["Hora"] == "20:00"
    assert legacy_event["Nome formatado da loja"] == "Loja Piloto nº 12"
    result = render_event_card(legacy_event, legacy_store, str(tmp_path))
    assert result.path.endswith(".jpg")
    assert (tmp_path / "bode_event_card_10.jpg").exists()
