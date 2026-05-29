import urllib3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from api_gsc_glpi.worker import executar_loop

if __name__ == "__main__":
    executar_loop()
