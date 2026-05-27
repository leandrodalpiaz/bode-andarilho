import os
import re

ROOT_DIR = r"d:\Repos\bode-andarilho"
EXCLUDE_DIRS = {".git", "venv", "__pycache__", "tmp", "output", "scratch", "assets"}

# List of words without accents that should have accents
# We use word boundaries \b to avoid matching parts of words.
WORDS = [
    (r"\bnao\b", "não"),
    (r"\bsao\b", "são"),
    (r"\bsessao\b", "sessão"),
    (r"\bsessoes\b", "sessões"),
    (r"\birmao\b", "irmão"),
    (r"\birmaos\b", "irmãos"),
    (r"\bmaconaria\b", "maçonaria"),
    (r"\bmaconico\b", "maçônico"),
    (r"\bmaconica\b", "maçônica"),
    (r"\bpotencia\b", "potência"),
    (r"\bpotencias\b", "potências"),
    (r"\binformacoes\b", "informações"),
    (r"\binformacao\b", "informação"),
    (r"\bconfirmacao\b", "confirmação"),
    (r"\binscricao\b", "inscrição"),
    (r"\binscricoes\b", "inscrições"),
    (r"\bconfiguracao\b", "configuração"),
    (r"\bconfiguracoes\b", "configurações"),
    (r"\bopcao\b", "opção"),
    (r"\bopcoes\b", "opções"),
    (r"\bvoce\b", "você"),
    (r"\bsecretario\b", "secretário"),
    (r"\bsecretaria\b", "secretaria/secretária"),
    (r"\bhorario\b", "horário"),
    (r"\bagape\b", "ágape"),
    (r"\bconfirmado\b", "confirmado"), # Just examples
    (r"\bja\b", "já"),
    (r"\bate\b", "até"),
    (r"\bsera\b", "será"),
    (r"\bha\b", "há"),
    (r"\bproximo\b", "próximo"),
    (r"\bproxima\b", "próxima"),
    (r"\bultimo\b", "último"),
    (r"\bultima\b", "última"),
    (r"\bcodigo\b", "código"),
    (r"\bnumero\b", "número"),
    (r"\bso\b", "só"),
    (r"\balem\b", "além"),
    (r"\bpos\b", "pós"),
]

def main():
    compiled_words = [(re.compile(p, re.IGNORECASE), repl) for p, repl in WORDS]
    
    for root, dirs, files in os.walk(ROOT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if not file.endswith((".py", ".md")):
                continue
            
            filepath = os.path.join(root, file)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except:
                continue
            
            for i, line in enumerate(lines):
                # Ignore import lines or pure python keywords to avoid false positives on variables
                if line.strip().startswith(("import ", "from ", "def ", "class ", "return ")):
                    # wait, return can have strings. 
                    pass
                
                # We only really care about strings in quotes or comments, but regex is easier.
                found_issues = []
                for regex, repl in compiled_words:
                    if regex.search(line):
                        found_issues.append(f"{repl}")
                
                if found_issues:
                    out.write(f"{file}:{i+1} -> found: {', '.join(found_issues)} | {line.strip()}\n")

if __name__ == "__main__":
    with open(r"d:\Repos\bode-andarilho\scratch\grammar_issues.txt", "w", encoding="utf-8") as out:
        main()
