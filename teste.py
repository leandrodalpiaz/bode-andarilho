from src.sheets import listar_eventos

eventos = listar_eventos()
print(f"{len(eventos)} evento(s) encontrado(s):")
for e in eventos:
    print(e)
