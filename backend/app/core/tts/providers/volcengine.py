import base64
import uuid

import httpx

from .utils import get_nested


async def synthesize_volcengine(
    *,
    text: str,
    output_path: str,
    base_url: str,
    app_id: str,
    token: str,
    cluster: str,
    voice: str,
    encoding: str,
) -> str:
    endpoint = f"{base_url.rstrip('/')}/api/v1/tts"
    headers = {"Authorization": f"Bearer;{token}", "Content-Type": "application/json"}
    body = {
        "app": {"appid": app_id, "token": token, "cluster": cluster},
        "user": {"uid": "smartclip"},
        "audio": {"voice_type": voice, "encoding": encoding, "rate": 24000},
        "request": {
            "reqid": uuid.uuid4().hex,
            "text": text,
            "text_type": "plain",
            "operation": "query",
        },
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(endpoint, headers=headers, json=body)

    data = resp.json()
    audio_b64 = get_nested(data, "data")
    if not audio_b64:
        raise RuntimeError(f"火山引擎 TTS 响应异常: {str(data)[:300]}")

    with open(output_path, "wb") as f:
        f.write(base64.b64decode(audio_b64))
    return output_path
