import asyncio
import sys
import os

sys.path.insert(0, 'f:\\LuoXi-Project\\LX_SmartClip\\backend')

async def main():
    from app.db.init_db import init_db, DB_PATH
    await init_db()
    print('DB init: OK')
    print(f'DB path: {DB_PATH}')
    print(f'DB file exists: {os.path.exists(DB_PATH)}')

    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        rows = await cur.fetchall()
        tables = [r[0] for r in rows]
        print(f'Tables: {tables}')
        assert 'videos' in tables, 'videos table missing'
        assert 'clips' in tables, 'clips table missing'
        assert 'config' in tables, 'config table missing'
        print('Table check: OK')

        cur2 = await db.execute('SELECT key, value FROM config ORDER BY key')
        configs = await cur2.fetchall()
        print(f'Config rows: {len(configs)}')
        config_dict = {k: v for k, v in configs}
        expected_keys = [
            'split_mode', 'fixed_duration', 'scene_threshold',
            'vector_dimension', 'top_k', 'vlm_provider', 'vlm_base_url',
            'vlm_model', 'vlm_api_key', 'tts_provider', 'asr_model'
        ]
        for key in expected_keys:
            assert key in config_dict, f'Missing config key: {key}'
        print('Config keys check: OK')
        print('Default values:')
        for k, v in sorted(configs):
            print(f'  {k} = {repr(v)}')

asyncio.run(main())
print('\nAll Phase 1 checks PASSED.')
