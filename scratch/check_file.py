# scratch/check_file.py
import os

filepath = r"d:\Repos\bode-andarilho\src\sheets_supabase.py"
if not os.path.exists(filepath):
    print("File not found!")
    exit()

with open(filepath, "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
target_range = range(2640, 2675)
for i in target_range:
    if i < len(lines):
        print(f"{i+1}: {repr(lines[i])}")
