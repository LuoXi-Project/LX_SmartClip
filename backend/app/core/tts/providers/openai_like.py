import httpx


async def synthesize_openai_like(
    *,
    text: str,
    output_path: str,
    base_url: str,
    api_key: str,
    model: str,
    voice: str,
    response_format: str,
    app_key: str = "",
) -> str:
    endpoint = f"{base_url.rstrip('/')}/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if app_key:
        headers["X-DashScope-AppId"] = app_key

    body = {
        "model": model or "tts-1",
        "input": text,
        "voice": voice,
        "response_format": response_format,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(endpoint, headers=headers, json=body)

    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI TTS 请求失败: HTTP {resp.status_code} {resp.text[:200]}")

    with open(output_path, "wb") as f:
        f.write(resp.content)
    return output_path
