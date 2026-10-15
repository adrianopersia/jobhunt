---
name: review
description: Revisa postulaciones con CV ya adaptado. Audita el CV contra sus fuentes, lee el formulario de la empresa, propone respuestas y deja el paquete listo para enviar a mano. Usar después de /tailor, o cuando el usuario pide revisar o preparar postulaciones.
---

# /review

Tercer paso del pipeline: CV adaptado → auditoría y formulario → paquete listo para el candidato.

## Pasos

1. **Elegir postulaciones.** Las que el usuario nombró, o todas las que figuran como `tailored`
   en `.venv/bin/jobhunt app list`.
2. **Revisar en paralelo.** Un subagente `application-reviewer` por postulación, todos en el
   mismo mensaje. A cada uno pasale solo el ID del aviso.
3. **Corregir lo que haga falta.** Por cada postulación en `needs_changes` por el CV, lanzá
   `cv-tailor` con el ID y las observaciones del revisor (están en `review.md`). Después volvé
   a revisarla. Como máximo dos vueltas: si sigue en `needs_changes`, se la dejás al usuario.
4. **Resultado.** `.venv/bin/jobhunt app list` y, por cada postulación, una línea con el
   veredicto, la ruta de `review.md` y qué tiene que decidir el usuario.

## Reglas

- El envío lo hace el usuario. Ningún paso abre formularios en un navegador ni envía datos.
- Si una postulación necesita información que el perfil no tiene, por ejemplo el permiso de
  trabajo, juntá esas preguntas y hacéselas al usuario una sola vez, al final.
