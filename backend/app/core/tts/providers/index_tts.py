import httpx

from .utils import get_nested


async def synthesize_index_tts(
    *,
    text: str,
    output_path: str,
    base_url: str,
    ref_audio: str,
) -> str:
    endpoint = f"{base_url.rstrip('/')}/run/predict"
    body = {"data": [text, ref_audio]}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(endpoint, json=body)

    data = resp.json()
    audio_url = get_nested(data, "data.0.url") or get_nested(data, "data.0")
    if not audio_url:
        raise RuntimeError(f"IndexTTS 响应异常: {str(data)[:300]}")

    async with httpx.AsyncClient(timeout=60) as client:
        audio_resp = await client.get(audio_url)

    with open(output_path, "wb") as f:
        f.write(audio_resp.content)
    return output_path
