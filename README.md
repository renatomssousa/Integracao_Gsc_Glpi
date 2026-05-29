# api-gsc-glpi

Integracao entre CAIXA GSC e GLPI.

## Como executar

Configure as variaveis de ambiente com base em `.env.example` e rode:

```bash
poetry install
poetry run api-gsc-glpi
```

Para manter compatibilidade com o formato antigo, tambem funciona:

```bash
python main.py
```

## Estrutura

- `src/api_gsc_glpi/caixa_client.py`: cliente SOAP da CAIXA.
- `src/api_gsc_glpi/glpi_client.py`: cliente REST do GLPI.
- `src/api_gsc_glpi/worker.py`: orquestracao do ciclo CAIXA -> GLPI -> CAIXA.
- `src/api_gsc_glpi/glpi_updates.py`: estado local de mapeamentos, reiteracoes, status, followups e documentos.
- `src/api_gsc_glpi/processors.py`: parsing dos XMLs recebidos da CAIXA.
- `tests/`: testes automatizados iniciais para funcoes puras.
