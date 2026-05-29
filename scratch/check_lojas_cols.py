import os
from dotenv import load_dotenv

load_dotenv()

from src.sheets_supabase import supabase

def main():
    if not supabase:
        print("Supabase client not initialized.")
        return
        
    res = supabase.table("lojas").select("*").limit(1).execute()
    if res.data:
        print("Colunas da tabela 'lojas':")
        for k in res.data[0].keys():
            print(f"- {k}")
    else:
        print("Tabela vazia ou sem dados retornados.")

if __name__ == "__main__":
    main()
