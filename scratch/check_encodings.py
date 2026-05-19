import os
import re

# Directory to scan
ROOT_DIR = r"d:\Repos\bode-andarilho"

# Exclude list
EXCLUDE_DIRS = {".git", "venv", "__pycache__", "tmp", "output"}

# Mojibake patterns in UTF-8
# These are strings that happen when UTF-8 bytes are incorrectly decoded as latin1/windows-1252 and then encoded to UTF-8.
# For example:
# 'ã' is UTF-8: \xc3\xa3. If decoded as latin1, it is 'Ã\xa3' (Ã£).
# 'á' is UTF-8: \xc3\xa1. If decoded as latin1, it is 'Ã\xa1' (Ã¡).
# 'é' is UTF-8: \xc3\xa9. If decoded as latin1, it is 'Ã\xa9' (Ã©).
# 'í' is UTF-8: \xc3\xad. If decoded as latin1, it is 'Ã\xad' (Ã­).
# 'ó' is UTF-8: \xc3\xb3. If decoded as latin1, it is 'Ã\xb3' (Ã³).
# 'ú' is UTF-8: \xc3\xba. If decoded as latin1, it is 'Ã\xba' (Ãº).
# 'ç' is UTF-8: \xc3\xa7. If decoded as latin1, it is 'Ã\xa7' (Ã§).
# 'ê' is UTF-8: \xc3\xaa. If decoded as latin1, it is 'Ã\xaa' (Ãª).
# 'ô' is UTF-8: \xc3\xb4. If decoded as latin1, it is 'Ã\xb4' (Ã´).
# 'º' is UTF-8: \xc2\xba. If decoded as latin1, it is 'Â\xba' (Âº).
# 'ª' is UTF-8: \xc2\xaa. If decoded as latin1, it is 'Â\xaa' (Âª).

MOJIBAKE_PATTERNS = [
    r"Ã¡", r"Ã©", r"Ã­", r"Ã³", r"Ãº", r"Ã£", r"Ãµ", r"Ã§", 
    r"Ãª", r"Ã´", r"Ã¢", r"Ã ", r"Ã‰", r"Ã“", r"Ã‡", r"Ã ", 
    r"Ãƒ", r"Ã•", r"Âº", r"Âª", r"Ã¢"
]

pattern_regex = re.compile("|".join(MOJIBAKE_PATTERNS))

def check_file(filepath):
    # Try reading as UTF-8
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError as e:
        # Check if it can be decoded as latin1
        try:
            with open(filepath, "r", encoding="latin1") as f:
                content = f.read()
            return "NON_UTF8_LATIN1", []
        except Exception:
            return "UNKNOWN_ENCODING", []
    
    # Check for mojibake patterns
    lines = content.splitlines()
    matches = []
    for idx, line in enumerate(lines, 1):
        found = pattern_regex.findall(line)
        if found:
            matches.append((idx, line, list(set(found))))
            
    if matches:
        return "UTF8_WITH_MOJIBAKE", matches
    return "OK", []

def main():
    report = []
    for root, dirs, files in os.walk(ROOT_DIR):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if not file.endswith((".py", ".md", ".txt", ".json", ".html")):
                continue
            
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, ROOT_DIR)
            
            status, details = check_file(filepath)
            if status != "OK":
                report.append((rel_path, status, details))
                
    # Print report
    print(f"--- SCAN REPORT ({len(report)} files with issues) ---")
    for file, status, details in report:
        print(f"\nFile: {file} | Status: {status}")
        if status == "UTF8_WITH_MOJIBAKE":
            print(f"Found {len(details)} lines with possible mojibake:")
            for line_no, content, found in details[:10]: # limit to 10 for overview
                print(f"  Line {line_no}: {content.strip()}  (Found: {found})")
            if len(details) > 10:
                print(f"  ... and {len(details) - 10} more lines.")

if __name__ == "__main__":
    main()
