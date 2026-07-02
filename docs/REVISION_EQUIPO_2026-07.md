# 🔍 Revisión integral del repo — Julio 2026

> Revisión multidisciplinaria (lógica de negocio, ciberseguridad, UX/UI, ML,
> docs/DevOps) con testeo funcional en vivo y reconciliación contra una
> simulación real validada por el negocio. Cada hallazgo tiene archivo:línea
> para ir directo al código.

---

## 1. Veredicto ejecutivo

| Área | Nota | Resumen en una línea |
|---|:---:|---|
| Lógica core (simulador, ingesta, datos) | 7/10 | Motor de simulación excelente y validado 1:1 contra el negocio; la ingesta y el caching tienen modos de fallo silenciosos |
| Ciberseguridad | 7/10 | Muy por encima del promedio interno; queda un XSS almacenado real y el anti fuerza bruta es evadible |
| UX / UI | 7/10 | App madura y con identidad; se pierde TODO el estado al cambiar de módulo y el es-AR está incompleto |
| ML | 5/10 | Ingeniería cuidada alrededor de modelos con problemas de fondo: sin forecast real, leakage en una feature, módulo bloqueado por un puntero LFS roto |
| Docs / DevOps | 6/10 | CI y tests bien; README era de otra era (ya corregido en esta revisión) y hay inconsistencias entre documentos |

**Lo más importante:** el corazón del producto — el motor de simulación de
aumentos — **funciona y reproduce exactamente los números del negocio**
(ver §2). Los problemas serios están en los bordes: caching, ingesta,
seguridad del render, y el módulo ML.

---

## 2. Testeo funcional realizado (evidencia)

**Suite de tests:** `49 passed, 9 skipped` (los 9 son la regresión de negocio,
que requiere los `.xlsx` sensibles). `ruff check`: limpio.

**Regresión contra el Excel real del negocio** (workbook Hospital Italiano
jun-26 v2, provisto para esta revisión): los **3 tests de regresión PASAN**.
Verificación directa con `core.workbook_validacion.validar_workbook` sobre las
1.911 filas (1.738 Pauta):

| Escenario | Impacto anual | Impacto mensual | Impacto % | Desvío entre rutas |
|---|---:|---:|---:|---:|
| Solicitado | $ 1.164.279.590,86 | $ 97.023.299,24 | 7,4837 % | 0,00e+00 |
| Propuesto | $ 316.594.963,51 | $ 26.382.913,63 | 2,0350 % | 0,00e+00 |

La app reproduce el headline del workbook y el Valor Ofrecido fila a fila con
desvío cero (ruido de punto flotante). **El motor está validado.**

**Prueba en vivo (navegador headless):** la app levanta, el login con bcrypt
funciona end-to-end, el Inicio renderiza con las 3 cards y estado vacío claro,
y el Módulo 1 muestra la sección «Carga de datos» con checklist de pendientes.
Detectado en vivo: el Inicio dice "Abrí la sección «Carga de datos» del menú
izquierdo" pero esa sección **no existe en el Inicio** (solo dentro de los
módulos) — confirmado luego en código (§5, UX-A2).

---

## 3. Hallazgos de lógica core

### Alta

- **CORE-A1 · Caché de errores.** `src/core/data_loader.py:88-149` —
  `_query_table` atrapa la excepción DENTRO de la función cacheada y devuelve
  `None` → `st.cache_data` cachea ese `None` 10 minutos. Un lock transitorio
  deja los 3 módulos "sin datos" con datos existentes, y sin mensaje en los
  reruns siguientes. Contradice la nota de diseño de las líneas 152-160 (las
  otras funciones sí lo hacen bien). *Fix: dejar propagar y mover el
  try/except a un wrapper no cacheado.*
- **CORE-A2 · Colisión de clave de caché.** `src/core/cachekeys.py:27-34` —
  `df_fingerprint` = (filas, columnas, suma de numéricas). Un tarifario
  corregido donde solo cambió texto (Nomenclador, flag Pauta/No pauta) produce
  la MISMA clave → `get_merged_dataset` y la simulación cacheada sirven
  **resultados financieros viejos con confianza**. *Fix:
  `pd.util.hash_pandas_object(df, index=False).sum()` en la huella.*
- **CORE-A3 · Esquema de ingesta lo fija el primer archivo.**
  `scripts/ingest.py:101-123` — la tabla se crea con las columnas del primer
  archivo ingerido; `_align_to_table` descarta en silencio columnas nuevas de
  archivos posteriores. Perder `Tipo Clase CM` desactiva sin aviso el merge
  por ámbito (internación vs ambulatorio). *Fix: crear con esquema completo
  (`EXPECTED_*_COLS`) o `ALTER TABLE ADD COLUMN` + log de descartes.*
- **CORE-A4 · `data_loader.py` es UI dentro de core.** Renderiza sidebar,
  botones y spinners (`:246-344`, `:450-506`); imposible de testear o envolver
  en FastAPI (Fase 2 declarada en ARQUITECTURA.md). Explica sus 0 tests.

### Media (selección)

- **CORE-M1.** `simulator.py:62-65` — tarifa ilegible → `fillna(0)` → entra al
  merge como $0 y deflacta totales sin aparecer en la cobertura. Debe contar
  como cobertura faltante.
- **CORE-M3.** `scripts/ingest.py:94-98` — idempotencia por hash del archivo:
  si se ingirió con `--mes` equivocado, re-correr con el mes corregido da "ya
  ingerido"; solo `--rebuild` lo arregla. *Fix: identidad = hash + mes, o
  `--force`.*
- **CORE-M5.** `excel_utils.py:296-314` — `to_numeric_tolerante` asume formato
  US: un export es-AR ("1.234,56") se convierte en 1,23456 (÷1000 silencioso).
  *Fix: heurística de detección de patrón es-AR.*
- **CORE-M6.** `workbook_validacion.py:158-160` — hoja 'Simulación' vacía →
  `KeyError` crudo en vez de mensaje de negocio.
- **CORE-M7.** `simulator.py:289-333` — overrides por prestación en loop
  O(k·n); con miles de overrides sobre cientos de miles de filas se siente.
  *Fix: vectorizar con `.map()` + `np.where`.*
- **CORE-M11.** La regresión de negocio se saltea en CI (fixtures sensibles):
  `workbook_validacion.py` queda con 0 cobertura garantizada. *Fix: fixture
  sintético generado con openpyxl en el propio test.*

### Gaps de tests prioritarios

`data_loader` completo (0 tests), `scripts/ingest.py` (0 tests — CORE-A3
pasaría verde hoy), `apply_simulation(months≠1)` (el parámetro más peligroso,
sin test que fije semántica), `impact_metrics` degenerado (total 0/negativos).

---

## 4. Hallazgos de seguridad

> La base es sólida: sin secretos commiteados (verificado también en el
> historial git), SQL 100% parametrizado, bcrypt cost 12, subprocesos sin
> shell, uploads procesados en memoria sin path traversal, `.dockerignore`
> correcto.

- **SEC-A1 · XSS almacenado (ALTA).** `src/ui/simulator_controls.py:291-294`
  y `simulator_tabs.py:482` — el Nomenclador que viene de los DATOS se
  interpola en HTML con `unsafe_allow_html=True` sin `html.escape()`. Un
  export/upload con `<img src=x onerror=...>` como nombre de grupo ejecuta JS
  en el navegador de cualquier usuario que abra ese prestador. Agrava: la
  cookie de sesión (streamlit-authenticator) NO es HttpOnly → robable por JS.
  *Fix: escapar todo string derivado de datos en los ~17 usos de
  `unsafe_allow_html`; evaluar CSP vía Caddy.*
- **SEC-M2 · Anti fuerza bruta evadible.** `src/auth.py:29-32` — el CHEQUEO de
  lockout usa el username de la sesión anterior (o "global"), pero el REGISTRO
  del fallo usa el username recién tipeado: una sesión fresca por intento
  nunca cae en el bucket chequeado. Además, 5 fallos ajenos bloquean a un
  usuario legítimo (DoS de cuenta) y el estado es en memoria. *Fix: chequear
  por username intentado + límite por IP + persistencia.*
- **SEC-M3 · TLS a Supabase no forzado.** `src/core/db_remote.py:78-92` — DSN
  sin `sslmode=require` (default `prefer` = acepta downgrade). *Fix: forzar
  `require`/`verify-full`.*
- **SEC-M4 · Rol `postgres` en la app.** La conexión bypasea RLS y tiene
  privilegios totales; un DSN filtrado = proyecto Supabase completo. *Fix: rol
  read-only acotado al schema `simulador`.*
- **SEC-M5 · Modelo de amenazas desactualizado.** `DESPLIEGUE_SEGURO.md` dice
  "todo local, sin nube" pero Supabase manda datos a AWS; y la RLS que
  `SUPABASE.md` da por hecha no tiene DDL en el repo que la evidencie.
- **SEC-M6 · Bomba de descompresión.** `excel_utils.py:60-83` — el preview de
  encabezado parsea el xlsx completo sin `read_only=True`; 50 MB de zip pueden
  expandir a GB de XML (DoS por RAM, requiere usuario autenticado).
- **Menores:** `X-Forwarded-For` confiado sin allowlist del proxy
  (`audit.py:38-47`); CI sin `permissions: contents: read`;
  `gen_credentials.py` sigue pidiendo un `role` que la app ignora (falsa
  sensación de RBAC).

---

## 5. Hallazgos UX/UI

- **UX-A1 · Se pierde TODO el estado al cambiar de módulo (el mayor dolor
  real).** Navegación por `st.radio` (`streamlit_app.py:79-84`): al pasar de
  M1 a M2 y volver, prestador, meses, % de aumento, ajustes por prestación y
  exclusiones vuelven a default — rehacer la negociación entera. *Fix barato:
  keep-alive de keys `sim_*`/`anomaly_*` al inicio del entry point
  (re-asignar `st.session_state[k] = st.session_state[k]`).*
- **UX-A2 · Instrucción rota en Inicio** (confirmado en vivo): "Abrí la
  sección «Carga de datos»" pero el expander solo se renderiza dentro de los
  módulos (`data_loader.py:450`), no en Inicio.
- **UX-A3 · Tres patrones para elegir prestador** (inline con "TODOS" en M1,
  multiselect en tab en M2, expander de sidebar con "(Todos)" en M3): el
  usuario re-aprende la UI en cada módulo y el contexto no lo sigue.
- **UX-M1 · Semántica de color invertida.** `simulator_tabs.py:731-736` pinta
  el aumento de costo en VERDE (`st.success`) y la reducción en amarillo — al
  revés que el resto de la página; `ml_tabs.py:128` deja el delta default
  (sobreestimación en verde). 
- **UX-M2/M3 · es-AR incompleto.** Moneda perfecta, pero porcentajes con punto
  ("12.50%"), contadores US ("300,000 filas") y gráficos Plotly con
  separadores US conviven con "$1.234.567". *Fix: `format_pct()` en
  formatters + `separators=",."` en `theme.layout_base` (1 línea que arregla
  todos los gráficos).*
- **UX-M8 · Edición fantasma en el data_editor de prestaciones.**
  `simulator_controls.py:115-136` — key fija + filas que se reordenan al
  agregar una prestación: un $ editado puede quedar aplicado a OTRA
  prestación. En una herramienta de negociación es un error serio. *Fix: key
  derivada del set seleccionado.*
- **Menores:** login en inglés (streamlit-authenticator acepta `fields` en
  español), contraste #797979 aún en labels chicos (falla WCAG AA), copy
  contradictorio en tab Comparativa, `MESES_ES` duplicado en 3 archivos,
  cachés sin `max_entries` en anomaly_tabs (fuga de memoria en sesiones
  largas).

---

## 6. Hallazgos ML

- **ML-A1 · Módulo 3 bloqueado por puntero LFS roto.**
  `models/scalers_pablo.pkl` es un puntero Git LFS sin resolver (130 bytes) y
  `module3.py:28-43` corta el módulo ENTERO si falta cualquier archivo —
  aunque los 3 LightGBM (sanos, verificados) alcanzan para predecir. El
  Dockerfile copia `models/` sin `git lfs pull` → la imagen hereda el puntero
  roto. *Fix: degradar a LightGBM-only + resolver/commitear el pkl real.*
- **ML-A2 · Leakage del target.** `ml_predictor.py:167` — `fue_activo` indica
  si la entidad facturó EN el mes que se predice (para cantidad,
  `fue_activo=0 ⇔ cantidad=0`): el R²=0,94 de cantidad está inflado y en un
  forecast real esa feature es desconocida. *Fix: re-entrenar sin ella (los
  `activo_lag_*` sí son legítimos).*
- **ML-A3 · No hay forecast: es un backtest.** `construir_panel`
  (`ml_predictor.py:159`) arma el calendario solo hasta el último mes
  observado; el tab "Predicción" muestra meses históricos re-puntuados
  (probablemente los mismos del entrenamiento), no costo futuro. *Fix:
  extender el panel a t+1 con lags del pasado y graficarlo como forecast.*
- **ML-M1 · Irreproducible.** No hay script/notebook de entrenamiento en el
  repo; split 78/22 sin documentar; sin versionado de modelos.
- **ML-M2 · Sin incertidumbre.** Predicciones puntuales; el "Error %" compara
  sumas mensuales (los errores por fila se cancelan y luce mejor que el MAE
  real). *Fix: LightGBM quantile P10/P90 + banda en el gráfico.*
- **ML-M3/M4 · Anomalías:** el método percentil marca el máximo de CADA grupo
  por construcción (grupos de 1 registro = 100% anómalos → exigir n≥5); serie
  plana que pega un salto da z=inf → NaN → NO se marca (el caso más obvio es
  falso negativo).
- **Menores:** TensorFlow (~200 MB) para una red de ~350 parámetros que pierde
  contra LightGBM en las 3 métricas (portar pesos a numpy o retirarla);
  `load_lightgbm` no valida archivos corruptos no-LFS; 0 tests del feature
  engineering (lags/calendario), justo donde la paridad con Colab es crítica.

---

## 7. Docs / DevOps

- **README reescrito en esta revisión** (era de la era "Fase 1 en curso, solo
  DuckDB"): ahora refleja las 3 fuentes de datos, auth, ingesta por bandeja,
  CI, LFS, despliegue y roadmap real.
- Inconsistencias pendientes entre documentos:
  - `CÓMO_CORRERLO.md` dice v0.5.2 (app está en v0.6.0) y describe un "paquete
    con credenciales y datos" que un clone limpio NO trae (falta el paso
    `gen_credentials.py`).
  - `ARQUITECTURA.md` dice "Fase 1 ✅ en curso" (¿hecho o en curso?) y lista
    como futuro un conector Postgres que ya existe.
  - `DESPLIEGUE_SEGURO.md` §4 dice "considerar rate-limit" — ya está
    implementado.
  - `gen_credentials.py` emite un campo `role` que la doc declara eliminado.
- Gaps: sin LICENSE (front-matter dice `license: other`); sin tags de git ni
  CHANGELOG (v0.6.0 vs v0.5.2 en 3 archivos); Python 3.11 no declarado
  formalmente (sin `requires-python`); rutas personales hardcodeadas en
  `deploy/run_secure.ps1:17` y `Caddyfile:18`; CI sin badge (agregado al
  README nuevo) y sin `permissions:`.

---

## 8. Qué implementaría (roadmap priorizado)

### 🔴 Ahora (bugs con impacto en números o seguridad — 1-2 días)

1. **`html.escape()` en todo render de datos** con `unsafe_allow_html`
   (SEC-A1) — es un XSS almacenado real con cookie robable.
2. **Endurecer `df_fingerprint`** con hash de contenido (CORE-A2) — es la vía
   más probable de "números viejos mostrados con confianza", el peor fallo
   posible en esta app.
3. **Arreglar el caching de errores de `_query_table`** (CORE-A1) — patrón ya
   resuelto en el mismo archivo, es mover el try/except.
4. **Arreglar el lockout** (SEC-M2): chequear por username intentado + límite
   por IP.
5. **Desbloquear el Módulo 3**: degradar a LightGBM-only cuando falte la red
   (ML-A1) y resolver el pkl de LFS.

### 🟡 Próximo sprint (robustez y confianza)

6. **Blindar la ingesta** (CORE-A3, CORE-M3): esquema completo al crear
   tablas, re-ingesta con mes corregido, y tests de `_upsert`/`_align_to_table`
   con DuckDB temporal.
7. **Persistir el estado entre módulos** (UX-A1) + arreglar la instrucción de
   Inicio (UX-A2) + key dinámica en el data_editor (UX-M8).
8. **Fixture sintético para `workbook_validacion`** (CORE-M11): que la
   reconciliación de negocio tenga cobertura en CI sin datos sensibles.
9. **Supabase:** `sslmode=require`, rol read-only, verificar RLS real
   (SEC-M3/M4/M5).
10. **Cerrar es-AR** (UX-M2/M3): `format_pct` + `separators=",."` + semántica
    de color coherente (UX-M1).

### 🟢 Después (producto)

11. **Forecast ML real**: panel extendido a t+1, re-entrenar sin `fue_activo`,
    split temporal documentado, script de entrenamiento versionado, intervalos
    P10/P90. Hasta entonces, renombrar el tab a "Backtest" para no
    sobre-prometer.
12. **Fase 0 de verdad en `data_loader`**: separar consulta pura de
    renderizado (CORE-A4) — habilita tests y la Fase 2 (FastAPI).
13. **Unificar patrón de filtros** entre módulos (UX-A3) y extraer componentes
    compartidos (selector de prestador, estados vacíos, `MESES_ES`).
14. **Higiene DevOps**: LICENSE, CHANGELOG + tags, `permissions` en CI,
    actualizar CÓMO_CORRERLO/ARQUITECTURA/DESPLIEGUE_SEGURO, quitar el `role`
    fantasma de `gen_credentials.py`.

---

*Revisión realizada el 2026-07-02 sobre la rama
`claude/repo-review-recommendations-7psq2r` (base: main @ 3048951).*
