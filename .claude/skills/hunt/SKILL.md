---
name: hunt
description: Corre el ciclo completo de búsqueda laboral, pensado para arrancar en una sesión nueva. Trae avisos nuevos, los analiza, arma CVs y deja paquetes de postulación listos para enviar a mano. Usar cuando el usuario dice /hunt, "arrancá un ciclo" o "busquemos trabajo de nuevo".
---

# /hunt

Un ciclo completo: fuentes → análisis → selección → CVs → revisión → resumen. Todo el estado
vive en `private/` (base, perfil, postulaciones), así que no hace falta contexto de sesiones
anteriores.

## 0. Contexto del ciclo anterior

1. `ls private/runs/ciclo-*.md`: el más reciente es el ciclo anterior y la fecha está en el
   nombre. Si no hay ninguno, es el primer ciclo y no hay fecha `--since`.
2. `.venv/bin/jobhunt app list`. En un solo mensaje, preguntale al usuario:
   - cuáles de las `ready` envió (avisale que las que no, se borran al cerrar el ciclo);
   - si hubo novedades en las `submitted`: respuesta, entrevista o rechazo.
   Actualizá con `.venv/bin/jobhunt app set <id> --status <submitted|interviewing|offer|rejected>
   --note "<novedad>"`. Seguí con el paso 1 mientras tanto; la limpieza del cierre espera la
   respuesta.

## 1. Avisos nuevos

**LinkedIn.** Si el conector de Gmail está disponible (herramientas `mcp__claude_ai_Gmail__*`),
lanzá el subagente `linkedin-inbox` con N = días desde el ciclo anterior (como máximo 30). Si
no está disponible, avisale al usuario que autorizando el conector de Gmail en claude.ai se suman
sus alertas de LinkedIn, y seguí. Nunca leas Gmail desde el hilo principal: solo ese subagente,
y bajo el hook que lo limita a emails de LinkedIn.

Si el usuario pasó links de avisos que encontró por su cuenta, sumalos con
`.venv/bin/jobhunt add <url> ...`; si pegó el texto de un aviso de LinkedIn, con
`jobhunt add --paste`. Después seguí `.claude/skills/scout/SKILL.md`
(bajar de todas las fuentes, analizar en paralelo y ranking).

## 2. Selección

`.venv/bin/jobhunt report --new --decision apply maybe --since <fecha del ciclo anterior>`.
Mostrá la tabla y preguntá cuáles seguir. Por defecto van todos los `apply`, con un máximo de 5
por ciclo. Si nadie responde (corrida programada, sin una persona del otro lado), seguí con el
default.

## 3. CVs

Seguí `.claude/skills/tailor/SKILL.md` con los avisos elegidos.

## 4. Revisión

Seguí `.claude/skills/review/SKILL.md` con los mismos avisos.

## 5. Cierre

1. **Limpieza.** `.venv/bin/jobhunt app clean --before <fecha de hoy>` muestra el plan: borra las
   carpetas de lo que no se envió en ciclos anteriores y de los procesos rechazados. Lo enviado y
   lo que está en entrevista se conserva, y también todo lo de este ciclo. Ejecutalo con `--apply`
   solo si el usuario ya contestó cuáles envió. Si no contestó, mostrale el plan y dejalo para el
   próximo ciclo.
2. `.venv/bin/jobhunt digest --since <fecha del ciclo anterior>` y guardalo en
   `private/runs/ciclo-<fecha de hoy>.md`.
3. Mostrale al usuario:
   - los paquetes listos, con la ruta de cada `review.md`;
   - lo que tiene que decidir en cada uno, con el salario recomendado;
   - las postulaciones cuyo aviso se cerró;
   - los avisos de LinkedIn que esperan texto (`jobhunt linkedin pending`), con el link de cada uno;
   - el recordatorio: cuando envíe, que avise para marcarlas como `submitted`.

## Reglas

- Ningún paso envía postulaciones, completa formularios en la web ni escribe a empresas.
- No se modifican el perfil ni las preferencias sin que el usuario lo pida.
- Si un paso falla (una fuente caída, un formulario ilegible), se sigue con el resto y se
  avisa en el cierre.
