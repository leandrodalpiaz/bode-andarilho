# scratch/test_galeria.py
import os
import sys
from datetime import datetime

# Adiciona o diretorio pai ao sys.path para conseguir importar os modulos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.render_marcos import renderizar_badge_wall

def run_mock_rendering_test():
    print("🚀 Iniciando Teste de Renderização da Galeria de Conquistas...")
    
    # 1. Construir dados simulados
    mock_dados = {
        "nome_loja": "Loja Mock da Fraternidade 999",
        "conquistas_individuais": [
            {"slug": "rs", "titulo": "Iniciado na Região", "descricao": "Confirmou presença pela primeira vez", "desbloqueada": True},
            {"slug": "rc", "titulo": "Rei da Caravana", "descricao": "Mais de 3 visitas confirmadas", "desbloqueada": True},
            {"slug": "pj", "titulo": "Pilar da Jornada", "descricao": "Assiduidade absoluta no ano", "desbloqueada": False},
            {"slug": "ce", "titulo": "Coluna da Eloquência", "descricao": "Apresentou 3 peças de arquitetura", "desbloqueada": True},
            {"slug": "e9", "titulo": "Estrela dos Nove", "descricao": "Visitou 9 lojas distintas", "desbloqueada": False},
            {"slug": "og", "titulo": "Obreiro Global", "descricao": "Expandiu conexões para outros países", "desbloqueada": False},
            {"slug": "mp", "titulo": "Mestre dos Passos", "descricao": "Andarilho consagrado", "desbloqueada": True},
            {"slug": "na", "titulo": "Navegador das Arcadas", "descricao": "Interagiu com todo o ecossistema", "desbloqueada": False},
            {"slug": "ic", "titulo": "Insignia do Conhecimento", "descricao": "Respondeu 10 questionários", "desbloqueada": True},
            {"slug": "pm", "titulo": "Protetor do Malhete", "descricao": "Venerável Mestre do ano", "desbloqueada": False},
            {"slug": "io", "titulo": "Intendente da Oficina", "descricao": "Secretário Destaque", "desbloqueada": False}
        ],
        "marcos_oficina": [
            {"mes_formatado": "Maio/2026", "excelencia": True, "farol": True},
            {"mes_formatado": "Abril/2026", "excelencia": True, "farol": False},
            {"mes_formatado": "Março/2026", "excelencia": False, "farol": True}
        ],
        "marcos_expansao": [
            {"titulo": "Expansão Sul", "slug": "expansao_geo|rs"},
            {"titulo": "Arco Rito York", "slug": "arco_integracao|york"}
        ]
    }
    
    nome_membro = "Ir. Leandro D'Alpiaz"
    nome_loja = "Augusta e Respeitável Loja Simbólica de Teste"
    
    # 2. Disparar renderizacao
    print("🎨 Processando canvas 1200x675 com Pillow...")
    try:
        caminho_resultado = renderizar_badge_wall(mock_dados, nome_membro, nome_loja)
        
        if caminho_resultado and os.path.exists(caminho_resultado):
            tamanho = os.path.getsize(caminho_resultado)
            print(f"✅ Sucesso! Quadro gerado em: {caminho_resultado}")
            print(f"📦 Tamanho do arquivo: {tamanho / 1024:.2f} KB")
            
            # Em ambiente local, poderíamos manter para inspeção, mas em produção seria excluído
            print(f"💡 Verifique visualmente a composição do arquivo gerado.")
        else:
            print("❌ Falha crítica: O caminho retornado não existe ou é vazio.")
            
    except Exception as e:
        import traceback
        print(f"💥 Exceção capturada durante o teste:")
        traceback.print_exc()

if __name__ == "__main__":
    run_mock_rendering_test()
