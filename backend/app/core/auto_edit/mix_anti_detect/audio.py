"""音频防检测：Librosa 频谱混淆 + FFmpeg 滤镜。"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid

import numpy as np

from app.core.auto_edit.mix_anti_detect.scheduler import RuntimeParams
from app.models.auto_edit import MixAntiDetectAudioConfig
from app.utils.ffmpeg_utils import run_ffmpeg

logger = logging.getLogger(__name__)


def _write_wav_pcm16(path: str, stereo: np.ndarray, sr: int) -> None:
    """stereo: shape (samples, channels) float [-1,1]"""
    import wave

    pcm = np.clip(stereo * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(pcm.shape[1] if pcm.ndim > 1 else 1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _read_wav_stereo(path: str) -> tuple[np.ndarray, int]:
    """返回 shape (samples, channels) float32 [-1, 1]。"""
    import wave

    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch <= 1:
        mono = pcm.reshape(-1, 1)
        return np.concatenate([mono, mono], axis=1), sr
    return pcm.reshape(-1, nch), sr


def _numpy_fingerprint_obfusc(wav_path: str, params: RuntimeParams, cfg: MixAntiDetectAudioConfig) -> str:
    """无 librosa 时的频谱混淆回退：预加重 + 底噪 + 轻量相位抖动。"""
    stereo, sr = _read_wav_stereo(wav_path)
    rng = np.random.default_rng(abs(hash(params.seed)) % (2**32))
    noise_amp = 10 ** (params.noise_floor_db / 20.0)
    out = stereo.copy()

    for ch in range(out.shape[1]):
        x = out[:, ch]
        if cfg.enable_phase_eq:
            coef = 0.97 + 0.02 * float(rng.random())
            pre = np.empty_like(x)
            pre[0] = x[0]
            pre[1:] = x[1:] - coef * x[:-1]
            x = 0.85 * x + 0.15 * pre
        # 轻量「频谱」扰动：块级随机增益
        block = max(256, sr // 100)
        for i in range(0, len(x), block):
            gain = 1.0 + rng.uniform(-0.04, 0.04) * params.gain
            x[i : i + block] *= gain
        x += rng.normal(0, noise_amp, size=x.shape)
        out[:, ch] = np.clip(x, -1.0, 1.0)

    tmp = os.path.join(tempfile.gettempdir(), f"ad_audio_{uuid.uuid4().hex[:8]}.wav")
    _write_wav_pcm16(tmp, out, sr)
    return tmp


def _librosa_fingerprint_obfusc(wav_path: str, params: RuntimeParams, cfg: MixAntiDetectAudioConfig) -> str:
    import librosa

    y, sr = librosa.load(wav_path, sr=None, mono=False)
    if y.ndim == 1:
        channels = [y]
    else:
        channels = [y[i] for i in range(y.shape[0])]

    rng = np.random.default_rng(abs(hash(params.seed)) % (2**32))
    out_channels = []
    for ch in channels:
        stft = librosa.stft(ch, n_fft=2048, hop_length=512)
        mag, phase = np.abs(stft), np.angle(stft)
        phase_noise = rng.normal(0, 0.08 * params.gain, size=phase.shape)
        stft2 = mag * np.exp(1j * (phase + phase_noise))
        recon = librosa.istft(stft2, hop_length=512, length=len(ch))

        noise_amp = 10 ** (params.noise_floor_db / 20.0)
        recon = recon + rng.normal(0, noise_amp, size=recon.shape)

        if cfg.enable_phase_eq:
            eq = librosa.effects.preemphasis(recon, coef=0.97 + 0.02 * rng.random())
            recon = 0.85 * recon + 0.15 * eq

        out_channels.append(np.clip(recon, -1.0, 1.0))

    if len(out_channels) == 1:
        stereo = np.stack([out_channels[0], out_channels[0]], axis=1)
    else:
        stereo = np.stack(out_channels, axis=1)
    tmp = os.path.join(tempfile.gettempdir(), f"ad_audio_{uuid.uuid4().hex[:8]}.wav")
    _write_wav_pcm16(tmp, stereo, sr)
    return tmp


def _fingerprint_obfusc(wav_path: str, params: RuntimeParams, cfg: MixAntiDetectAudioConfig) -> str:
    try:
        import librosa  # noqa: F401

        return _librosa_fingerprint_obfusc(wav_path, params, cfg)
    except ImportError:
        logger.info("librosa 未安装，使用 NumPy 频谱混淆回退")
        return _numpy_fingerprint_obfusc(wav_path, params, cfg)


def _build_ffmpeg_audio_filter(params: RuntimeParams, cfg: MixAntiDetectAudioConfig) -> str:
    filters: list[str] = []

    if cfg.enable_segment_speed and params.speed_factors:
        # 链式 atempo（每段平均）
        avg = float(np.mean(params.speed_factors))
        avg = float(np.clip(avg, 0.85, 1.15))
        filters.append(f"atempo={avg:.4f}")

    if cfg.enable_reverb_pitch and abs(params.pitch_cents) > 0.5:
        semitones = params.pitch_cents / 100.0
        # rubberband 非所有 FFmpeg 构建均包含；asetrate 为通用回退
        rate_factor = 2 ** (semitones / 12.0)
        filters.append(f"asetrate=44100*{rate_factor:.6f},aresample=44100")

    if cfg.enable_reverb_pitch and params.reverb_mix > 0.01:
        wet = min(0.45, params.reverb_mix)
        filters.append(
            f"aecho=0.8:0.88:{int(40 + wet * 80)}:{wet:.3f}"
        )

    if cfg.enable_phase_eq:
        filters.append("extrastereo=m=1.08")
        filters.append("equalizer=f=1200:width_type=o:width=2:g=0.6")
        filters.append("aphaser=in_gain=0.8:out_gain=0.74:delay=2.5:decay=0.35:speed=0.45")

    if cfg.enable_fingerprint_obfusc:
        filters.append("highpass=f=35")
        filters.append("lowpass=f=16500")

    return ",".join(filters) if filters else ""


def process_audio_file(
    wav_path: str,
    cfg: MixAntiDetectAudioConfig,
    params: RuntimeParams,
    work_dir: str,
) -> str:
    if not cfg.enabled:
        return wav_path

    os.makedirs(work_dir, exist_ok=True)
    intermediate = wav_path

    if cfg.enable_fingerprint_obfusc or cfg.enable_phase_eq:
        try:
            intermediate = _fingerprint_obfusc(wav_path, params, cfg)
        except Exception as e:
            logger.warning("频谱混淆失败，跳过: %s", e)
            intermediate = wav_path

    af = _build_ffmpeg_audio_filter(params, cfg)
    out = os.path.join(work_dir, "audio_processed.wav")
    args = ["-i", intermediate, "-ac", "2", "-ar", "44100"]
    if af:
        args += ["-af", af]
    args += ["-c:a", "pcm_s16le", out]

    try:
        run_ffmpeg(args, desc="anti-detect audio filters")
    except Exception as e:
        logger.warning("FFmpeg 音频滤镜失败，回退 Librosa 输出: %s", e)
        if intermediate != wav_path and os.path.isfile(intermediate):
            import shutil

            shutil.copy2(intermediate, out)
        else:
            import shutil

            shutil.copy2(wav_path, out)

    if intermediate != wav_path and os.path.isfile(intermediate):
        try:
            os.remove(intermediate)
        except OSError:
            pass

    return out
