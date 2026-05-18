import sys
import os

# Add src folder to the python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.ritos import normalizar_rito, RITOS_OFICIAIS

print("Official Rites List:", RITOS_OFICIAIS)
print("-" * 50)

test_cases = [
    # REAA
    ("REAA", "REAA"),
    ("reaa", "REAA"),
    ("Escocês", "REAA"),
    ("Rito Escocês Antigo e Aceito", "REAA"),
    
    # York
    ("York", "York"),
    ("rito de york", "York"),
    
    # Schröder
    ("Schröder", "Schröder"),
    ("Schroeder", "Schröder"),
    ("rito schroder", "Schröder"),
    
    # Escocês Retificado
    ("Escocês Retificado", "Escocês Retificado"),
    ("escocês retificado", "Escocês Retificado"),
    ("Rito Escocês Retificado", "Escocês Retificado"),
    ("retificado", "Escocês Retificado"),
    ("rer", "Escocês Retificado"),
    
    # MLAA
    ("MLAA", "MLAA"),
    ("MALAA", "MLAA"),
    ("Maçons Livres Antigos e Aceitos", "MLAA"),
    ("macons livres antigos aceitos", "MLAA"),
    ("Rito MLAA", "MLAA"),
    
    # Other / None
    ("Outro", ""),
    ("Qualquer outro rito desconhecido", ""),
]

success = True
for input_str, expected in test_cases:
    result = normalizar_rito(input_str)
    if result == expected:
        print(f"[OK] '{input_str}' -> '{result}'")
    else:
        print(f"[FAIL] '{input_str}' -> Got '{result}', Expected '{expected}'")
        success = False

print("-" * 50)
if success:
    print("All normalization tests PASSED successfully!")
else:
    print("Some normalization tests FAILED.")
