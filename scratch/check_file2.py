# scratch/check_file2.py
import os

filepath = r"d:\Repos\bode-andarilho\src\sheets_supabase.py"
with open(filepath, "rb") as f:
    content = f.read()

lines = content.split(b"\n")
print(f"Line 2674 binary: {repr(lines[2673])}")
