---
name: tailor
description: Arma CVs adaptados para avisos ya analizados, con subagentes cv-tailor en paralelo, y muestra el resultado. Usar cuando el usuario pide CVs para avisos, "adaptá el CV", o después de /scout.
---

# /tailor

Segundo paso del pipeline: aviso analizado → CV anclado al perfil → carpeta de postulación.

## Pasos

1. **Elegir avisos.** Si el usuario nombró avisos, usá esos IDs. Si no, los de
   `.venv/bin/jobhunt report --decision apply` que todavía no tengan carpeta en
   `.venv/bin/jobhunt app list`. Si hay más de 5, preguntá antes de lanzar.
2. **Adaptar en paralelo.** Un subagente `cv-tailor` por aviso, todos en el mismo mensaje.
   A cada uno pasale solo su ID.
3. **Resultado.** `.venv/bin/jobhunt app list`, y debajo una tabla por aviso: idioma, titular,
   puntaje de keywords, excluyentes no cubiertos y ruta del PDF.

## Reglas

- No edites el perfil para que un CV pase el verificador. Si un subagente cree que al perfil le
  falta algo cierto, que lo diga: el perfil lo actualiza el candidato.
- Los PDFs quedan en `private/applications/`; no se copian a ningún archivo versionado.
