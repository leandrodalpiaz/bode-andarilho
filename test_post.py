import sys
import asyncio
from fastapi.testclient import TestClient
sys.path.append("d:/Repos/bode-andarilho")

def run_test():
    try:
        from main import fastapi_app
        client = TestClient(fastapi_app)
        
        payload = {
            "telegram_id": "123456789",
            "data": "23/12/2026",
            "horario": "20:00",
            "grau": "1",
            "tipo_sessao": "Magna",
            "nome_loja": "Teste",
            "numero_loja": "1",
            "oriente": "Curitiba",
            "rito": "REAA",
            "potencia": "GOB",
            "endereco": "Rua x",
            "agape": "Sim",
            "observacoes": "Teste obs",
            "traje": "Balandrau"
        }
        
        print("Sending POST request...")
        response = client.post("/api/cadastro_evento", json=payload)
        print("Response:", response.status_code, response.json())
        
    except Exception as e:
        print("TEST ERROR:", e)

if __name__ == "__main__":
    run_test()
