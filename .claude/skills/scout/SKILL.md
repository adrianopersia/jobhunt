---
name: scout
description: Busca avisos nuevos en las fuentes configuradas, los analiza contra el perfil del candidato con subagentes job-scout en paralelo y muestra el ranking. Usar cuando el usuario pide buscar trabajos, actualizar avisos o ver el ranking.
---

# /scout

Orquesta el primer paso del pipeline: fuentes → filtro previo → análisis → ranking.

## Pasos

1. **Bajar avisos.** Por cada fuente (hoy: `startups_argentina`):
   `.venv/bin/jobhunt fetch <fuente>`
   Tarda: el cliente hace un request por vez con pausa. Si el agregador no tiene la descripción,
   la busca en el ATS de la empresa y deja el aviso en `pending` para re-analizarlo. Reportá el
   resumen que imprime, incluidos los avisos con `description_unavailable`.
2. **Ver pendientes.** `.venv/bin/jobhunt pending`. Si no hay, saltá al paso 4.
3. **Analizar en paralelo.** Partí los IDs en lotes de hasta 8 y lanzá un subagente `job-scout`
   por lote, todos en el mismo mensaje. A cada uno pasale solo su lista de IDs.
4. **Ranking.** `.venv/bin/jobhunt report --decision apply maybe` y mostralo.
   Debajo, en 3 a 5 líneas: cuántos avisos quedaron en cada decisión, los motivos de descarte
   más frecuentes, y cualquier aviso que un subagente no pudo analizar.

## Reglas

- No cambies `private/preferences.yaml` ni la rúbrica para que "entren" más avisos. Si los
  filtros parecen mal calibrados, decilo y proponé el cambio.
- El ranking es para el candidato; no lo copies a archivos versionados.
