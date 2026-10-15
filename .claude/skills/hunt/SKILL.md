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
2. `.venv/bin/jobhunt app list`. Si hay postulaciones `submitted`, preguntale al usuario en un
   solo mensaje si hubo novedades: respuesta, entrevista o rechazo. Actualizá con
   `.venv/bin/jobhunt app set <id> --status <estado> --note "<novedad>"`. No frenes el ciclo
   esperando la respuesta.

## 1. Avisos nuevos

Si el usuario pasó links de avisos que encontró por su cuenta (LinkedIn, referidos), sumalos
primero con `.venv/bin/jobhunt add <url> ...`. Después seguí `.claude/skills/scout/SKILL.md`
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

1. `.venv/bin/jobhunt digest --since <fecha del ciclo anterior>` y guardalo en
   `private/runs/ciclo-<fecha de hoy>.md`.
2. Mostrale al usuario:
   - los paquetes listos, con la ruta de cada `review.md`;
   - lo que tiene que decidir en cada uno, con el salario recomendado;
   - las postulaciones cuyo aviso se cerró;
   - el recordatorio: cuando envíe, que avise para marcarlas como `submitted`.

## Reglas

- Ningún paso envía postulaciones, completa formularios en la web ni escribe a empresas.
- No se modifican el perfil ni las preferencias sin que el usuario lo pida.
- Si un paso falla (una fuente caída, un formulario ilegible), se sigue con el resto y se
  avisa en el cierre.
