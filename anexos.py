from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from api_gsc_glpi.anexos import *  # noqa: F401,F403
