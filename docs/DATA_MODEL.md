# Modelo de datos

La aplicación trabaja con dos datasets de entrada en formato Excel (`.xlsx`):
**Consumo** y **Valores**. Ambos se cargan vía `core/data_loader.py`, que
autodetecta la fila de encabezado y normaliza tipos en `core/simulator.py`.

## 1. Dataset de Consumo (`consumo.xlsx`)

Registro de consumo médico por prestador, convenio, mes y prestación.

| Columna | Tipo | Descripción |
| ------- | ---- | ----------- |
| `Prestador ID` | entero | Identificador del prestador. |
| `Prestador Desc` | texto | Nombre del prestador. |
| `Convenio ID` | entero | Identificador del convenio. |
| `Convenio Desc` | texto | Descripción del convenio. |
| `Mes` | texto `MM-YYYY` | Período del registro. |
| `Tipo Categoria` | texto | Categoría del afiliado/plan. |
| `Megacuenta` | texto | Agrupador comercial. |
| `Gama` | texto | Gama del plan. |
| `Cartilla` | texto | Cartilla asociada. |
| `Tipo Clase CM` | texto | Clase de costo médico. |
| `Nomenclador` | texto | Nomenclador de la prestación. |
| `Prestacion Desc` | texto | Descripción de la prestación. |
| `Prestacion ID` | entero | Identificador de la prestación. |
| `Cantidad CM` | numérico | Cantidad de prestaciones. |
| `Importe CM` | numérico | Importe total facturado. |

## 2. Dataset de Valores (`valores.xlsx`)

Tarifas convenidas por prestador y prestación.

| Columna | Tipo | Descripción |
| ------- | ---- | ----------- |
| `Prestador ID` | entero | Identificador del prestador. |
| `Prestador Desc` | texto | Nombre del prestador. |
| `Convenio ID` | entero | Identificador del convenio. |
| `Convenio Desc` | texto | Descripción del convenio. |
| `Prestacion ID` | entero | Identificador de la prestación. |
| `Prestacion Desc` | texto | Descripción de la prestación. |
| `Mes Vigencia` | texto | Mes de vigencia del valor. |
| `Valor Convenido a HOY` | numérico | Tarifa convenida vigente. |

## 3. Merge

Consumo y Valores se unen por las claves:

```
MERGE_KEYS = ["Prestador ID", "Convenio ID", "Prestacion ID"]
```

Antes del merge, `normalize_dataframes`:

- Fuerza las claves a `Int64` (admite nulos).
- Convierte columnas numéricas (`Cantidad CM`, `Importe CM`,
  `Valor Convenido a HOY`) a numérico, coercionando inválidos a `NaN`.

El resultado alimenta:

- **Módulo 1**: cálculo de `Consumo Ideal`, `Consumo Simulado`, `Valor
  Ofrecido`, `% Aumento`.
- **Módulo 2**: serie temporal y comparación estructural (solo requiere
  Consumo).
- **Módulo 3**: panel Prestador × Prestación × Mes con calendario completo para
  el feature engineering de ML.

## 4. Métrica de "precio unitario"

Varios cálculos derivan el precio unitario como:

```
precio_unitario = Importe CM / Cantidad CM   (cuando Cantidad CM > 0)
```

En la agregación mensual del Módulo 3 se usa un **promedio ponderado por
cantidad** para evitar sesgos.

## 5. Datos externos

- **Inflación INDEC** (`core/indec.py`): serie IPC Nacional, variación mensual,
  desde la API de datos.gob.ar. Se usa para contextualizar aumentos en el
  Módulo 1.

> Los datasets reales **no se versionan** (ver `SECURITY.md`). Este documento
> describe el contrato de columnas que la app espera; los archivos se proveen en
> runtime.
