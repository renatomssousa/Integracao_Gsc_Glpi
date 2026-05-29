from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from api_gsc_glpi.reprocessar_anexos_caixa import *  # noqa: F401,F403


if __name__ == "__main__":
    from api_gsc_glpi import glpi_client
    from api_gsc_glpi.reprocessar_anexos_caixa import reprocessar_aberturas, reprocessar_reiteracoes

    glpi_client.init_session()
    try:
        reprocessar_aberturas()
        reprocessar_reiteracoes()
    finally:
        glpi_client.kill_session()
