"""List files in the Supabase storage bucket under a given prefix.

Usage:
  python scripts/list_files.py 09862580-fda6-4910-b70b-7803cde2a68a
"""
import asyncio
import sys

from app.utils.supabase_storage import supabase_storage


async def main(prefix: str):
    loop = asyncio.get_running_loop()

    def _sync_list():
        try:
            return supabase_storage.client.storage.from_(supabase_storage.bucket_name).list(path=prefix)
        except Exception as e:
            return {"error": str(e)}

    result = await loop.run_in_executor(None, _sync_list)
    print(result)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/list_files.py <prefix>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
