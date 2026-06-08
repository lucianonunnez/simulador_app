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

Esta info **refuerza el plan de migrar los datos a Supabase (Fase 1)**:

- **El límite de 1M filas de MicroStrategy y el bajar "de a partes" es exactamente
  el dolor que Supabase elimina.** Una vez que los datos están en Postgres:
  - No hay límite de export → se consulta solo lo que se necesita.
  - El trade-off del "Caso 1 vs Caso 2" se diluye: con índices en Postgres podés
    tener **todo** y que igual sea **rápido** (consultás por prestador/período, no
    cargás el millón de filas a memoria como hace pandas hoy).
- **La comparativa por coordinación (Mejora 1)** se vuelve trivial en SQL: es un
  `JOIN` con una tabla de coordinaciones + filtro. Conviene modelar la tabla de
  **coordinaciones/coordinadores** desde el principio del esquema.
- **La estrategia de actualización (Decisión A)** define el **pipeline de ingesta**:
  el script que sube el Excel de MicroStrategy a Supabase puede correr manual
  (cuando bajan datos nuevos) o programado cada 3 meses.

> 💡 **Sugerencia para la reu:** en vez de plantear "rápido pero incompleto vs
> completo pero lento" (Caso 1 vs Caso 2 con la arquitectura actual de Excel),
> se puede plantear **"migramos a una base de datos y dejamos de elegir"** — tenés
> todo Y rápido. El costo es armar la ingesta una vez.

---

## 8. ❓ Cosas a confirmar
- ¿Quiénes son exactamente "Alfon", "Ceci", "Bevi"? (¿coordinaciones? ¿responsables?)
- ¿Qué es "tipo C" y "tipo I" de prestador?
- ¿"La distri" = qué reporte/vista exacta en MicroStrategy?
- Pedir a **Nati** los listados de categorías de honorarios individuales.
- Definir con el equipo: Decisión A y Decisión B (sección 4).
