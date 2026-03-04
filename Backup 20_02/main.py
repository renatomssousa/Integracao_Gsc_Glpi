import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from worker import executar_loop

if __name__ == "__main__":
    executar_loop()
