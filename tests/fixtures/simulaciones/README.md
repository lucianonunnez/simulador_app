# Fixtures de simulaciones reales del negocio

Estos workbooks contienen **precios de prestadores (datos sensibles)** y por eso
**no se versionan** (ver `.gitignore`). Sirven para la regresión de
`tests/test_simulaciones_negocio.py`, que reconcilia la lógica de la app contra
los números ya resueltos por el equipo de negociación.

## Cómo correr la regresión

Dejá los `.xlsx` en esta carpeta con estos nombres:

- `Simulacion_Hospital_Italiano_jun26.xlsx`
- `Simulacion_1130_Feb26.xlsx`
- `Simulacion_1127_Dic25.xlsx`

(o exportá `SIM_FIXTURES_DIR=/ruta/a/los/workbooks`). Luego:

    PYTHONPATH=src pytest tests/test_simulaciones_negocio.py -v

Sin los archivos, los tests se **saltean** (no rompen CI).
