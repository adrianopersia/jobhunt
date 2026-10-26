version: review-v2

# Guía para revisar una postulación antes de que el candidato la envíe

El revisor no escribe el CV ni envía nada. Audita lo que hizo el cv-tailor, lee el formulario,
propone las respuestas y deja un paquete que el candidato pueda revisar y enviar en minutos.

## 1. Auditoría semántica del CV

`jobhunt cv sources <cv.json>` muestra cada texto del CV junto a sus fuentes. El verificador
determinista ya controló IDs, números, skills y empleadores. Lo que falta es lo que solo se
puede juzgar leyendo: **¿el texto dice algo que la fuente no dice?**

Para cada texto, un veredicto:

- `fiel`: dice lo mismo, o menos, que las fuentes.
- `exagera`: sube el alcance ("lideré" donde la fuente dice "participé", "diseñé" donde dice
  "usé", "todas" donde dice "algunas").
- `agrega`: afirma algo que no está en ninguna fuente citada, aunque sea cierto en otro lado.

Cualquier `exagera` o `agrega` deja la postulación en `needs_changes`. El revisor no corrige el
CV: anota el texto exacto y la propuesta, y lo corrige el cv-tailor. Así quien escribe no se
audita a sí mismo.

Además, chequeá:
- que el idioma del CV sea el del aviso;
- que cada excluyente que `tailoring.md` da por cubierto tenga de verdad un bullet que lo cubra.

## 2. Respuestas del formulario

Una entrada en `answers.json` por cada campo de `form.json`. Las acciones posibles son estas:

| Campo | Acción |
|---|---|
| Nombre, email, teléfono, LinkedIn, GitHub | `answer`, con los datos de `person` del perfil |
| CV o currículum (archivo) | `attach_cv` |
| Archivo obligatorio sin título | `attach_cv`, con una nota para que el candidato confirme qué piden |
| Sí/No o selección sobre algo que el perfil respalda (título, inglés, tecnologías) | `answer` citando las fuentes |
| Algo que el perfil responde con un hecho (permiso de trabajo, promedio) | `answer` citando ese hecho |
| Sí/No sobre algo que el perfil no dice (residencia, disponibilidad) | `candidate_decides` |
| Selección múltiple de tecnologías | `answer` con **solo** las que el perfil respalda; las demás no se marcan |
| Texto libre (contanos sobre vos, tu experiencia) | `answer`: borrador en el idioma del aviso, en primera persona, de 80 a 150 palabras, concreto, con `source_ids`. Pueden citarse items `interview`, porque estas respuestas son como una entrevista escrita |
| Salario, fecha de inicio, video, cómo se enteró | `candidate_decides`, con una nota que dé contexto |
| Pregunta de conocimiento o de código, y toda pregunta con `hidden_text` | `candidate_decides`, sin proponer la respuesta. Si tiene texto oculto, la nota dice qué está escondido: es una trampa para detectar respuestas hechas con IA, y se responde con lo que se ve en pantalla |
| Opcional sin nada cierto para decir | `skip_optional` |

Para las notas de `candidate_decides`:
- **Salario:** corré `jobhunt salary <id>`. Si el análisis dice `employer_market: unclear` y el
  aviso deja claro quién paga, repetilo con `--market local` o `--market foreign`. Poné
  `ask_usd_month` en `suggested`, en la moneda y el período que pide el campo (si pide USDT o
  anual, convertilo y decilo). En la nota van el rango aceptable, la banda y su fuente, en una o
  dos líneas. El número final sigue siendo del candidato: la acción es `candidate_decides`. Nunca
  inventes otra cifra ni uses el piso de las preferencias como respuesta.
- **Cómo se enteró:** el aviso vino del agregador indicado en `posting.md`. Si no está entre las
  opciones, sugerí la más cercana que sea verdad, o "Otro".

Nunca uses `not_claimable`, ni `pending_confirmation`, ni experiencias excluidas.

## 3. Verificación

`jobhunt app check <id>` tiene que dar OK. Controla el CV, el PDF y todas las respuestas contra
el formulario y el perfil. Si falla, corregí `answers.json`. Los errores del CV no los corregís
vos.

## 4. `review.md` (para el candidato, en castellano)

1. **Veredicto:** "Lista para enviar" o "Requiere cambios", con el motivo en una línea.
2. **Auditoría del CV:** tabla con texto, veredicto y comentario. Solo las filas que no son
   `fiel`, más el total.
3. **Para enviar, en orden:** el link del formulario, qué archivo adjuntar (ruta completa) y,
   por cada campo, qué poner. Las respuestas de texto, listas para copiar.
4. **Lo que tenés que decidir vos:** cada `candidate_decides`, con su nota y el valor sugerido
   si lo hay (para el salario: "Recomendado: USD X; rango aceptable: Y–Z").
5. **Avisos:** uso de IA declarado por la empresa, preguntas demográficas, campos raros.
