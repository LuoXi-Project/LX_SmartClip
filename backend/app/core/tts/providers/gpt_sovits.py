import httpx


async def synthesize_gpt_sovits(
    *,
    text: str,
    output_path: str,
    base_url: str,
    ref_audio: str,
    ref_text: str,
    lang: str,
) -> str:
    params = {
        "refer_wav_path": ref_audio,
        "prompt_text": ref_text,
        "prompt_language": lang,
        "text": text,
        "text_language": lang,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(base_url.rstrip("/"), params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"GPT-SoVITS 请求失败: HTTP {resp.status_code}")

    with open(output_path, "wb") as f:
        f.write(resp.content)
    return output_path
