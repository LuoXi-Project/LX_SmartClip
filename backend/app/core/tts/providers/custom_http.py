import json as _json

import httpx

from .utils import get_nested


async def synthesize_custom_http(
    *,
    text: str,
    output_path: str,
    method: str,
    url_template: str,
    headers_raw: str,
    body_template: str,
    response_type: str,
    audio_key: str,
) -> str:
    """
    Custom HTTP TTS:
    - GET or POST
    - {text} placeholder in URL and body
    - Headers as JSON string
    - Response: binary (direct audio) or json (extract URL by dot-path then download)
    """
    url = url_template.replace("{text}", text)

    headers: dict = {}
    if headers_raw.strip():
        try:
            headers = _json.loads(headers_raw)
        except Exception:
            raise RuntimeError(f"请求头 JSON 解析失败: {headers_raw[:200]}")

    async with httpx.AsyncClient(timeout=60) as client:
        if method.upper() == "POST":
            body_str = body_template.replace("{text}", text) if body_template.strip() else None
            body_data = None
            if body_str:
                try:
                    body_data = _json.loads(body_str)
                except Exception:
                    raise RuntimeError(f"请求体 JSON 解析失败: {body_str[:200]}")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
            resp = await client.post(url, headers=headers, json=body_data)
        else:
            resp = await client.get(url, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"自定义 HTTP TTS 请求失败: HTTP {resp.status_code} {resp.text[:200]}")

    content_type = resp.headers.get("content-type", "")
    if response_type == "binary" or "audio" in content_type or "octet-stream" in content_type:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path

    try:
        data = resp.json()
    except Exception:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path

    audio_url = get_nested(data, audio_key) if audio_key else None
    if not audio_url:
        raise RuntimeError(f"JSON 响应中未找到路径 '{audio_key}'，响应体: {str(data)[:300]}")

    async with httpx.AsyncClient(timeout=60) as client:
        audio_resp = await client.get(str(audio_url))

    if audio_resp.status_code != 200:
        raise RuntimeError(f"下载音频 URL 失败: HTTP {audio_resp.status_code}")

    with open(output_path, "wb") as f:
        f.write(audio_resp.content)
    return output_path
