"""Self-check for prepare_whisper.ps1 (avoid PS 5.1 here-string / encoding issues)."""
import sys

try:
    import torch
    import whisper
except ImportError as e:
    print(f"import error: {e}", file=sys.stderr)
    sys.exit(1)

cuda_build = bool(torch.version.cuda)
cuda_runtime = torch.cuda.is_available()
wver = getattr(whisper, "__version__", "unknown")
print(f"torch={torch.__version__} cuda_build={cuda_build} cuda_runtime={cuda_runtime}")
print(f"whisper={wver}")
