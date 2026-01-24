# Re-export for backward compatibility
from .config import Config  # noqa: F401
# Optionally expose secret_config when present in this package
try:
    from .secret_config import *  # noqa: F401,F403
except Exception:
    pass
