version: tailor-v1

# Guía para adaptar el CV a un aviso

El objetivo es que el primer filtro, sea un ATS, un LLM o una persona leyendo 10 segundos, vea
rápido que el candidato cumple lo que el aviso pide. **Sin decir nada que el perfil no respalde.**
Un CV que pasa el filtro con una afirmación falsa se cae en la entrevista y quema la empresa.

## 1. Fidelidad (no negociable)

- Solo items del perfil con `use: cv`. Se puede reformular, acortar, fusionar dos items y
  reordenar. No se pueden agregar hechos, números, tecnologías, títulos ni empleadores.
- Cada bullet y el resumen citan en `source_ids` los items de donde salen. Si un bullet fusiona
  dos items, cita los dos.
- `jobhunt cv render` corre el verificador de anclaje y se niega a generar el PDF si falla. No
  se trabaja alrededor de un error: se corrige el texto.
- Nada de texto oculto, keywords repetidas para inflar, ni frases dirigidas al filtro ("ideal
  candidate", "perfect match"). Eso se detecta y descalifica.

## 2. Idioma

El CV va en `posting_language` del análisis. Partí del texto del perfil en ese idioma; no
traduzcas libremente desde el otro.

## 3. Titular

Uno de `headlines` del perfil, en el idioma del CV. Elegí el que más se parezca al título del
aviso. El verificador rechaza cualquier otro.

## 4. Resumen (2 o 3 oraciones)

- La primera oración responde al primer excluyente del aviso con hechos (`facts`): años, rol,
  contexto.
- Después, lo que más diferencia al candidato *para este aviso*: por ejemplo, el trabajo con
  agentes de IA si el aviso lo pide, o el trabajo de punta a punta si pide full-stack.
- Usá el vocabulario del aviso cuando el hecho lo respalde: si el aviso dice "de punta a punta"
  y el perfil dice "end to end", usá la forma del aviso.

## 5. Skills

- Primera línea: el stack central del aviso que el candidato tiene, en el orden en que lo nombra
  el aviso.
- Todo lo que `jobhunt cv keywords` liste en `missing_but_supported` tiene que entrar, si existe
  como skill del perfil.
- Lo de `missing_gap_do_not_add` no entra nunca, ni con otro nombre.
- Los nombres de skills se copian tal cual del perfil (el verificador los compara). Los rótulos
  de cada línea son libres.

## 6. Experiencia

- Todos los empleadores confirmados del perfil, en orden cronológico inverso. Si un hecho del
  resumen exige un empleador (`requires_companies`), ese empleador no se puede sacar.
- En el empleo actual, entre 6 y 8 bullets. Elegilos por los `evidence` del análisis del scout:
  primero los que cubren excluyentes, después los deseables, después el resto.
- Ordená los bullets por relevancia para este aviso, no por fecha.
- Cada bullet: verbo de acción al principio, 2 líneas como máximo, el número más fuerte adentro.
- En empleos anteriores, 1 a 3 bullets.

## 7. Proyectos, educación e idiomas

Proyectos solo si suman al aviso (por ejemplo, web o SEO si el aviso lo pide). Educación e
idiomas se copian del perfil.

## 8. Una página

Si el render da más de una página, sacá primero el bullet menos relevante y después acortá.
Nunca achiques la tipografía ni los márgenes.

## 9. Notas de adaptación (`tailoring.md`)

Para el candidato, en castellano:
- Cobertura de keywords: puntaje de `jobhunt cv keywords` y qué quedó afuera por ser hueco.
- Excluyentes del aviso: cuáles cubre el CV y con qué bullet; cuáles no.
- Qué preparar para la entrevista o la carta: los huecos reales y cómo encararlos con honestidad.
- Decisiones de adaptación que no son obvias: titular elegido, bullets que quedaron afuera.
