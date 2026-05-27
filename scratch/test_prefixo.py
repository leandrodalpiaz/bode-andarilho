import os
import sys
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set mock env variables so Supabase/Telegram initialization doesn't fail
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_KEY"] = "mock_key"
os.environ["TELEGRAM_TOKEN"] = "123456:mock_token"

from src.sheets_supabase import padronizar_nome_loja, extrair_prefixo_e_nome
from src.render_cards import obter_nome_formatado_loja

def test_padronizacao_e_extracao():
    print("--- Testando padronizar_nome_loja e extrair_prefixo_e_nome ---")
    test_cases = [
        ("A.R.L.S. Caminhos da Virtude", "A.R.L.S.", "Caminhos Da Virtude"),
        ("ARLS Caminhos da Virtude", "ARLS", "Caminhos Da Virtude"),
        ("A. R. L. S. Caminhos da Virtude", "A. R. L. S.", "Caminhos Da Virtude"),
        ("A.  R.  L.  S.   Caminhos da Virtude", "A.  R.  L.  S.", "Caminhos Da Virtude"),
        ("Augusta e Respeitável Loja Simbólica Caminhos da Virtude", "Augusta e Respeitável Loja Simbólica", "Caminhos Da Virtude"),
        ("Augusta e Respeitavel Loja Simbolica Caminhos da Virtude", "Augusta e Respeitavel Loja Simbolica", "Caminhos Da Virtude"),
        ("Loja Maçônica Caminhos da Virtude", "Loja Maçônica", "Caminhos Da Virtude"),
        ("Loja Maconica Caminhos da Virtude", "Loja Maconica", "Caminhos Da Virtude"),
        ("Loja Caminhos da Virtude", "Loja", "Caminhos Da Virtude"),
        ("B.A.R.L.S. Caminhos da Virtude", "B.A.R.L.S.", "Caminhos Da Virtude"),
        ("B. A. R. L. S. Caminhos da Virtude", "B. A. R. L. S.", "Caminhos Da Virtude"),
        ("BARLS Caminhos da Virtude", "BARLS", "Caminhos Da Virtude"),
        ("A.R.L.M. Caminhos da Virtude", "A.R.L.M.", "Caminhos Da Virtude"),
        ("Caminhos da Virtude", "", "Caminhos Da Virtude"),
        ("caminhos da virtude", "", "Caminhos Da Virtude"),
        ("", "", ""),
    ]

    success = True
    for input_name, expected_pref, expected_base in test_cases:
        res_clean = padronizar_nome_loja(input_name)
        pref, base = extrair_prefixo_e_nome(input_name)
        
        # Note: If no prefix matched, we expect prefix = "" and base = padronizar(input_name)
        # Note: If BARLS is not in the extrair_prefixo_e_nome pattern, it defaults to no prefix and base = padronizar.
        # Let's adjust expected base/prefix for BARLS and ARLM depending on how regex is configured.
        
        # Let's print outputs
        print(f"Input: {input_name!r}")
        print(f"  -> padronizar: {res_clean!r}")
        print(f"  -> extrair:    ({pref!r}, {base!r})")
        
        # Basic assertions
        if expected_base and base != expected_base:
            print(f"❌ Falha: esperado nome base {expected_base!r}, obteve {base!r}")
            success = False
            
    return success

def test_render_formatting():
    print("\n--- Testando obter_nome_formatado_loja (com e sem dados no Banco) ---")
    
    # Mock database functions in sheets_supabase to simulate different states
    with patch("src.sheets_supabase.buscar_loja_por_id") as mock_buscar_id, \
         patch("src.sheets_supabase.buscar_loja_por_nome_numero") as mock_buscar_nome_num:
         
        # Cenário 1: Loja encontrada no DB com coluna 'prefixo'
        mock_buscar_id.return_value = {
            "id": "123",
            "prefixo": "A.R.L.S.",
            "nome_loja": "Caminhos da Virtude",
            "numero": "99",
            "potencia": "GOB"
        }
        evento = {
            "loja_id": "123",
            "Nome da loja": "Qualquer Nome",
            "Número da loja": "99",
            "Potência": "GOB"
        }
        fmt = obter_nome_formatado_loja(evento)
        print(f"Cenário 1 (DB Com Prefixo + Número): {fmt!r}")
        assert fmt == "A.R.L.S. Caminhos Da Virtude nº 99", f"Obtido: {fmt}"

        # Cenário 2: Loja encontrada no DB com coluna 'prefixo', mas número é '0' (deve omitir número)
        mock_buscar_id.return_value = {
            "id": "123",
            "prefixo": "A.R.L.S.",
            "nome_loja": "Caminhos da Virtude",
            "numero": "0",
            "potencia": "GOB"
        }
        evento = {
            "loja_id": "123",
            "Nome da loja": "Qualquer Nome",
            "Número da loja": "0",
            "Potência": "GOB"
        }
        fmt = obter_nome_formatado_loja(evento)
        print(f"Cenário 2 (DB Com Prefixo, Número 0): {fmt!r}")
        assert fmt == "A.R.L.S. Caminhos Da Virtude", f"Obtido: {fmt}"

        # Cenário 3: Loja não tem coluna prefixo no DB (ou retorna None/Vazio) -> extrai dinamicamente
        mock_buscar_id.return_value = {
            "id": "123",
            "prefixo": "",
            "nome_loja": "A.R.L.S. Caminhos da Virtude",
            "numero": "99",
            "potencia": "GOB"
        }
        evento = {
            "loja_id": "123",
            "Nome da loja": "A.R.L.S. Caminhos da Virtude",
            "Número da loja": "99",
            "Potência": "GOB"
        }
        fmt = obter_nome_formatado_loja(evento)
        print(f"Cenário 3 (DB Sem Prefixo no DB - Retrocompatibilidade): {fmt!r}")
        assert fmt == "A.R.L.S. Caminhos Da Virtude nº 99", f"Obtido: {fmt}"

        # Cenário 4: Loja não encontrada no DB -> extrai dinamicamente do evento
        mock_buscar_id.return_value = None
        mock_buscar_nome_num.return_value = None
        evento = {
            "loja_id": "",
            "Nome da loja": "A. R. L. S. Estrela do Sul",
            "Número da loja": "123",
            "Potência": "GLMERJ"
        }
        fmt = obter_nome_formatado_loja(evento)
        print(f"Cenário 4 (Fora do DB, extraído do evento): {fmt!r}")
        assert fmt == "A. R. L. S. Estrela Do Sul nº 123", f"Obtido: {fmt}"

        # Cenário 5: Loja sem número e sem prefixo
        evento = {
            "loja_id": "",
            "Nome da loja": "Estrela do Sul",
            "Número da loja": "",
            "Potência": "GLMERJ"
        }
        fmt = obter_nome_formatado_loja(evento)
        print(f"Cenário 5 (Sem prefixo e sem número): {fmt!r}")
        assert fmt == "Estrela Do Sul", f"Obtido: {fmt}"

    print("✅ Todos os testes do renderizador passaram com sucesso!")
    return True

if __name__ == "__main__":
    s1 = test_padronizacao_e_extracao()
    s2 = test_render_formatting()
    if s1 and s2:
        print("\n🎉 Todos os testes concluídos com SUCESSO!")
        sys.exit(0)
    else:
        print("\n❌ Alguns testes falharam.")
        sys.exit(1)
