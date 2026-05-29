from __future__ import annotations

import urllib3

from .worker import executar_loop


def main() -> None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    executar_loop()


if __name__ == "__main__":
    main()
