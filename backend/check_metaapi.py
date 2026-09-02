import asyncio
import os
import sys
from metaapi_cloud_sdk import MetaApi
from dotenv import load_dotenv

load_dotenv('backend/.env')

async def test():
    token = os.getenv("METAAPI_TOKEN", "")
    account_id = os.getenv("METAAPI_ACCOUNT_ID", "")
    
    if not token or not account_id:
        print("Missing token or account_id")
        return

    print(f"Token: {token[:10]}... Account: {account_id}")
    try:
        api = MetaApi(token)
        account = await api.metatrader_account_api.get_account(account_id)
        print(f"Account State: {account.state}")
        print(f"Connection Status: {account.connection_status}")
        
        if account.state != 'DEPLOYED':
            print("Deploying account...")
            await account.deploy()
            print("Deployed!")

        print("Waiting for API to synchronize (timeout=10s)...")
        conn = account.get_rpc_connection()
        await conn.connect()
        await asyncio.wait_for(conn.wait_synchronized(), timeout=10.0)
        
        print("✅ CONNECTION SYNCHRONIZED SUCCESSFULLY!")
        info = await conn.get_account_information()
        print("Account Info:")
        for k, v in info.items():
            print(f"  {k}: {v}")
            
    except asyncio.TimeoutError:
        print("❌ TIMEOUT ERROR: Connection is deployed but failing to synchronize with the broker (Exness).")
        print("Most likely your Exness MT5 server name, password, or login is incorrect, or the broker is offline.")
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__} - {e}")
        
if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test())
