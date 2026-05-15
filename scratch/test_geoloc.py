import sys
import os

# Garante que a pasta raiz está no path do Python
raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(raiz)

from src.location_service import calcular_distancia_haversine, filtrar_locais_por_raio

print("=" * 50)
print("VALIDANDO SERVIÇOS DE LOCALIZAÇÃO")
print("=" * 50)

# 1. Valida cálculo puro
dist = calcular_distancia_haversine(-29.33, -49.73, -29.33, -49.83) 
print(f"[OK] Cálculo Haversine executado. Distância teste: {dist:.2f} km")

# 2. Valida geocodificação e raio (Cidades vizinhas na divisa RS/SC)
print("\n[EXEC] Consultando coordenadas e filtrando por raio...")
destinos = [
    {"cidade": "Torres", "uf": "RS"},
    {"cidade": "Passo de Torres", "uf": "SC"},
    {"cidade": "Porto Alegre", "uf": "RS"},
    {"cidade": "Florianópolis", "uf": "SC"},
]

res = filtrar_locais_por_raio("Torres", "RS", destinos, raio_km=100.0)

print("\n[OK] Filtro Geográfico de 100km concluído!")
print("-" * 50)
for idx, r in enumerate(res):
    print(f"{idx+1}. {r['cidade']}-{r['uf']} -> {r['distancia_km']:.2f} km de distância.")
print("-" * 50)

assert len(res) >= 2, "Erro: Deveria encontrar pelo menos Torres e Passo de Torres."
print("\n[SUCCESS] Todo fluxo geográfico validado com sucesso!")
