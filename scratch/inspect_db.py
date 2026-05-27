import os
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def main():
    try:
        from src.sheets_supabase import supabase
        resp = supabase.table("lojas").select("prefixo").limit(1).execute()
        print("Success! prefixo column exists.")
    except Exception as e:
        print("Error checking prefixo column:", e)

if __name__ == "__main__":
    asyncio.run(main())
