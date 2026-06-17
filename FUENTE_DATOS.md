# 📥 Fuente de datos, extracción y decisiones — Simulador CM

> Notas organizadas a partir del mensaje del jefe. Cubre de dónde salen los datos,
> cómo bajarlos, las decisiones a plantear en la reunión y las primeras mejoras.

---

## 1. De dónde salen los datos

Los datos vienen de un reporte de **MicroStrategy** (no de un Excel suelto):

- **Servidor:** `strategy.swissmedical.com.ar` (requiere login)
- **Proyecto:** `SMMP_Costo Medico`
- **Hay DOS reportes:** uno de **Consumo** y uno de **Valores**.
- ⚠️ **Usar VPN sí o sí** — sin VPN funciona mal.
- **Fuente a usar:** "la distri" (la distribución).

### Cómo configurar la descarga
1. En cada reporte, **poner los prestadores** que se quieren bajar.
2. En el reporte de **Consumo**, **modificar el período**.
3. El **último mes disponible debería ser enero**.

---

## 2. Límite crítico: menos de 1 millón de filas

MicroStrategy revienta con el volumen. Regla práctica:

| Filas | ¿Funciona? |
|---|---|
| < 1.000.000 | ✅ Sí |
| ~1.100.000 | ⚠️ Aguanta |
| ~1.110.000 | ❌ Ya no |

**Por eso NO se baja todo de una** — hay que ir por partes (por grupos de prestadores
y/o acotando el período).

---

## 3. Guía de extracción por grupo de prestadores

> El criterio es ir **testeando** cuántos entran sin pasar el límite de filas.

| Grupo | Cómo bajarlos |
|---|---|
| **Los de Alfon** | De a **1**. (Se puede probar **trimestral** para meter más en una tirada.) |
| **Tipo C de Ceci** | Lógica parecida a Alfon: de a 1 / probar trimestral. |
| **Tipo I de Ceci y Bevi** | Probablemente se pueden bajar **de a varios** a la vez. |

Regla general: **ir testeando** combinaciones de prestadores + período hasta quedar
debajo del millón de filas.

---

## 4. Decisiones a plantear en la reunión

### Decisión A — Estrategia de actualización
- **Opción 1:** Guardar **copias** de los datos y dejar que **se actualice cada 3 meses**.
- **Opción 2:** **Preguntar qué prestadores** interesan y bajar **solo esos** (pediría
  **5 o 6**, porque una de las funciones es **comparar valores con prestadores similares**,
  así que hace falta más de uno).

### Decisión B — El gran trade-off (rendimiento vs completitud)
Plantear en la reu qué prefieren:

| | **Caso 1 (golazo)** | **Caso 2** |
|---|---|---|
| **Qué se guarda** | Solo **Valores** (es liviano, se baja en pocas tiradas) | **Todo** (Consumo + Valores) |
| **Velocidad** | ⚡ Rápido | 🐢 Más lento |
| **Actualización** | Fácil | Más trabajosa |
| **Contra** | Hay que bajar los consumos aparte | Más "paja" para funcionar/actualizar, pero no es la muerte |

---

## 5. Para la DEMO

Ir con un **grupo de prestadores comparables por coordinación**. Eso:
- Ahorra trabajo de descarga.
- Hace que la comparativa de valores tenga sentido (compara peras con peras).

---

## 6. Primeras mejoras (roadmap funcional)

### Mejora 1 — Agrupación por coordinaciones
- Subir, por ejemplo, **coordinadores** y que la app use esa info para la
  **comparativa de valores**, así compara con un **criterio**.
- **Por qué importa:** los prestadores de Ceci son lógicamente **mucho más caros**
  que los de Bevi → compararlos directo no sirve. Hay que comparar dentro de la
  misma coordinación.
- Se pueden **preguntar otros criterios** a tener en cuenta además de coordinación.

### Mejora 2 — Agrupación de honorarios individuales por categoría
- Agrupar los **individuales de honorarios por categoría**.
- Los **listados se le pueden pedir a Nati**.

---

## 7. 🔗 Cómo esto se conecta con la arquitectura (ver ARQUITECTURA.md)

Esta info **refuerza la decisión de mover los datos a DuckDB local (Fase 1)**.
DuckDB da los mismos beneficios que una base SQL en la nube, pero **sin sacar los
datos de la máquina** (clave por ser datos médicos sensibles → todo local):

- **El límite de 1M filas de MicroStrategy y el bajar "de a partes" es exactamente
  el dolor que la base elimina.** Una vez que los datos están en DuckDB:
  - No hay límite de export → se consulta solo lo que se necesita.
  - El trade-off del "Caso 1 vs Caso 2" se diluye: DuckDB es columnar e indexa,
    así que podés tener **todo** y que igual sea **rápido** (consultás por
    prestador/período, no cargás el millón de filas a RAM como hacía pandas).
- **La comparativa por coordinación (Mejora 1)** se vuelve trivial en SQL: es un
  `JOIN` con una tabla de coordinaciones + filtro. Conviene modelar la tabla de
  **coordinaciones/coordinadores** cuando se construya esa feature.
- **La estrategia de actualización (Decisión A)** define el **pipeline de ingesta**:
  `scripts/ingest.py` corre **manual** cada vez que bajás Excel nuevos (la política
  de IT prohíbe sincronización/automatización, así que manual es lo correcto).

> 💡 **Sugerencia para la reu:** en vez de plantear "rápido pero incompleto vs
> completo pero lento" (Caso 1 vs Caso 2 con la arquitectura de Excel), se puede
> plantear **"pasamos a una base de datos local y dejamos de elegir"** — tenés
> todo Y rápido, sin que los datos salgan de la máquina. El costo es armar la
> ingesta una vez (ya hecho). La nube (PostgreSQL) queda para cuando haya infra
> aprobada.

---

## 8. ❓ Cosas a confirmar
- ¿Quiénes son exactamente "Alfon", "Ceci", "Bevi"? (¿coordinaciones? ¿responsables?)
- ¿Qué es "tipo C" y "tipo I" de prestador?
- ¿"La distri" = qué reporte/vista exacta en MicroStrategy?
- Pedir a **Nati** los listados de categorías de honorarios individuales.
- Definir con el equipo: Decisión A y Decisión B (sección 4).

---

## 9. 📦 Formato CRUDO real de los exports (verificado contra archivos reales)

Los exports descargados de MicroStrategy **no** vienen con el contrato de columnas
de la app; el pipeline (`load_excel_smart` + `clean_dataset`) ahora tolera el
formato crudo automáticamente. Lo verificado con exports reales:

- **Formato y encoding variables por reporte**: CSV en UTF-8 con BOM (valores) o
  Mac OS Roman con finales de línea CR (consumo), además de xlsx. El loader
  detecta formato por contenido y elige encoding por heurística de letras
  españolas.
- **Columnas en pares estilo MicroStrategy**: cada atributo sale como columna
  nombrada + columnas `Unnamed: N` contiguas (`Prestador`/`Unnamed: 1`), con el
  orden ID/Desc **variable según el reporte**. `normalize_mstr_columns()` los
  mapea al contrato decidiendo por contenido.
- **Números como texto** con coma de miles, espacios y negativos contables:
  `"1,130 "`, `"23,653 "`, `"(5,477,196)"`. Los maneja `to_numeric_tolerante()`.
- **`Mes Vigencia` con nombres de mes en español** (`"Mayo 2026"`): se normaliza
  a `MM-YYYY` canónico.
- **Fila `Total` al final** del consumo: se descarta sola (clave no numérica).

**Limitaciones genuinas del export de consumo** (no resolubles por código,
requieren decisión de producto):
- **No trae columna `Mes`**: el período se elige al descargar y NO queda en
  ningún lado del archivo (verificado: la hoja "Mozart Reports" solo guarda la
  ruta del reporte y la fecha de descarga, no el filtro). Soluciones, de mejor
  a peor:
  1. **La definitiva (automática)**: agregar el atributo **Mes** al reporte
     `consumo` en MicroStrategy (ruta: `\SMMP_Costo Medico\Profiles\...\
     simulador\consumo`) — igual que el export curado histórico, que SÍ trae
     una fila por mes. Con eso no hay nada manual y las descargas multi-mes
     funcionan perfectas.
  2. Convención de nombre: `consumo 12-2025.xlsx` → la app precarga el mes.
  3. Manual: completar el campo "Mes de «archivo»" en la app (o `--mes` en el
     script). **Solo válido para descargas de UN mes**: asignarle un mes único
     a un export que abarca varios meses distorsiona la evolución temporal y
     el upsert.
- **No trae `Convenio ID`** (la columna `Convenio` trae un flag, no el ID).
  Pendiente: definir estrategia de merge (por `Convenio Desc`, o degradar a
  Prestador + Prestación resolviendo la vigencia más reciente).

---

## 10. 🏥 Internación: módulos día y valor por ámbito

Hallazgos de la revisión y de la simulación real del **Hospital Italiano**
(`Simulación Hospital Italiano jun26`), que conviene tener en cuenta al modelar:

### 10.1 Una prestación puede valer distinto según el ámbito
La **misma prestación** puede tener **distinto valor en Internación vs
Ambulatorio** ("no sale lo mismo"). El consumo distingue el ámbito en la
columna **`Tipo Clase CM`** (`Internación` / `Ambulatorio`), pero el export
de **valores** (tarifario) **hoy NO la trae**, así que ambos ámbitos comparten
el mismo valor.

- **Hecho (retrocompatible):** el merge (`core/simulator.merge_datasets`) ahora
  **suma `Tipo Clase CM` a la clave** cuando **ambos** lados la traen. Con los
  datos actuales (valores sin ámbito) el comportamiento es idéntico al de antes;
  cuando el tarifario empiece a traer el ámbito, cada combinación
  Prestador + Convenio + Prestación + Ámbito conserva su propio valor sin
  colapsar a uno solo.
- **Para que valga distinto por ámbito en serio:** el export de **valores** debe
  incluir la columna **`Tipo Clase CM`** (igual que el consumo). Es lo único que
  falta del lado de los datos; el motor ya está preparado.

### 10.2 Los módulos de internación no vienen en la base
Los **módulos día** de internación (por **Sala**: `UTI`, `UTI c/ARM`, `Clínica`,
`Pediatría`, `Cuidados Intermedios`, etc.) **no suelen venir en el tarifario
normal**. En la simulación del Hospital Italiano vienen en una **hoja aparte
(`Int`)**, con un **formato distinto** al del tarifario ambulatorio:

- Es **formato ancho**: una columna de valor **por mes de vigencia**
  (`Septiembre 2025`, `Octubre 2025`, …`Mayo 2026`) en vez del `Mes Vigencia`
  largo del tarifario normal.
- La clave es la **Sala Internación** (con su `idPrestacion` puesto en **0** en
  la hoja `Simulación`), no un código de prestación del nomenclador.
- Suele haber **dos líneas por sala** (estándar y "Black"/habitación individual)
  con valores propios.

**Requisito de datos (para una próxima fase):** para que internación entre a la
simulación automáticamente hay que **ingerir la hoja `Int`** como una fuente de
tarifas adicional, normalizándola al contrato (derretir los meses-columna a
`Mes Vigencia` + `Valor Convenido a HOY`, y mapear `Sala Internación` →
`Prestacion Desc`/`Prestacion ID`). Mientras tanto, el simulador trabaja sobre
las prestaciones que sí están en el tarifario; los módulos día quedan fuera
(equivale a tratarlos como "No pauta" si no hay tarifa).

### 10.3 Los aumentos (pauta) salen del INDEC
La **pauta** de aumento se baja del **INDEC** (IPC). En la simulación real, el
**"Valor propuesto"** se calcula como `Valor actual × (1 + pauta)` (verificado:
p. ej. consulta `18.626,16 × 1,021 = 19.017,31`), mientras que el **"Valor
solicitado"** es el **monto $** que pide el prestador. La app ya trae la
inflación del INDEC (`core/indec.py`, tab *Evolución* → "Contexto macro") para
usarla como referencia de pauta.
