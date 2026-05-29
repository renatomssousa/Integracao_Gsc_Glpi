from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from api_gsc_glpi.worker import *  # noqa: F401,F403


if __name__ == "__main__":
    from api_gsc_glpi.worker import executar_loop

    executar_loop()
