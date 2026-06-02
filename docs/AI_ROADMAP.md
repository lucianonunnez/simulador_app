# Roadmap de integración con IA

El simulador ya incorpora **modelos predictivos** (LightGBM y red neuronal) en
el Módulo 3. Este documento describe la siguiente etapa: un **copiloto
analítico** en lenguaje natural sobre los resultados de cada módulo, y la
evolución de las capacidades de ML.

> La base técnica ya está en el repositorio: `src/core/ai_assistant.py`,
> **desactivada por defecto**. El objetivo de este roadmap es llevarla a
> producción de forma segura e incremental.

## Visión

Que un ejecutivo pueda preguntar, en español, cosas como:

- *"¿Qué prestador explica el mayor desvío de costo en marzo?"*
- *"Resumime el impacto del escenario que acabo de simular."*
- *"¿La predicción de LightGBM y la red neuronal coinciden para este prestador?"*

…y obtener respuestas **fundamentadas en los datos que la app ya calculó**, no
en conocimiento genérico del modelo.

## Principios de diseño

1. **Grounding sobre datos propios.** El modelo recibe únicamente los agregados
   que el usuario ya ve (métricas, top-N, ranking de alertas, resumen del
   escenario). Nunca el dataset crudo ni columnas con PII.
2. **Opt-in y reversible.** Controlado por `AI_ASSISTANT_ENABLED` +
   `ANTHROPIC_API_KEY`. Si falta cualquiera, la app funciona igual.
3. **Dependencia aislada.** El SDK de Anthropic se importa de forma *lazy*; no
   pesa en la imagen mientras la feature esté apagada.
4. **Eficiencia.** Prompt caching sobre el bloque de sistema (estable) para
   abaratar y acelerar consultas repetidas.
5. **Trazabilidad.** Cada consulta se audita (`ai_query`) sin registrar el
   contenido del contexto.

## Estado actual (hecho)

- [x] Interfaz `ask(question, context)` con degradación elegante.
- [x] Resolución de configuración por entorno (`AssistantConfig.from_env`).
- [x] Prompt caching (`cache_control: ephemeral`) sobre el system prompt.
- [x] Auditoría de consultas.
- [x] Modelo por defecto: familia Claude 4.x (`claude-sonnet-4-6`).

## Hitos

### Hito A — Copiloto de lectura (read-only)
- [ ] Agregar `anthropic>=0.40.0` a un extra opcional de dependencias.
- [ ] Construir *context builders* por módulo que serialicen a texto los
      agregados ya calculados (métricas del simulador, ranking de alertas,
      comparativa de modelos).
- [ ] UI: un panel "Preguntá al asistente" en cada módulo, visible solo si
      `ai_assistant.is_available()`.
- [ ] Tests del armado de contexto (garantizar que no se filtre PII).

### Hito B — Explicaciones automáticas
- [ ] Resúmenes ejecutivos auto-generados ("3 hallazgos clave de este
      escenario").
- [ ] Explicación en lenguaje natural de por qué un registro fue marcado como
      desvío (combinando con la feature importance de LightGBM).

### Hito C — Interacción estructurada (tool use)
- [ ] Exponer funciones de `core` como *tools* para que el modelo pueda, por
      ejemplo, re-ejecutar una simulación con otros parámetros y comparar.
- [ ] Salidas estructuradas (JSON) para alimentar gráficos.

### Hito D — Pronóstico asistido
- [ ] Generación de narrativa sobre las proyecciones de ML.
- [ ] Detección de escenarios atípicos y alertas proactivas.

## Consideraciones de seguridad

- El contexto enviado al proveedor se limita a agregados; ver `SECURITY.md`.
- La API key se gestiona como secret/variable de entorno, nunca en el repo.
- Toda consulta queda auditada; se recomienda revisar periódicamente el volumen
  y el costo.
- Evaluar, según política de la organización, el uso de un endpoint con
  garantías de no-retención de datos.

## Métrica de éxito

Reducir el tiempo que un ejecutivo tarda en pasar de "ver el dashboard" a
"tener una conclusión accionable", manteniendo cero filtraciones de datos
sensibles.
