# jobhunt

Pipeline de agentes para búsqueda laboral: el scout analiza avisos contra un perfil, el
cv-tailor arma un CV anclado a evidencia por aviso, y el application-reviewer revisa cada
formulario de postulación. **El envío lo hace siempre la persona, a mano.** Ningún agente se
postula, completa formularios en el sitio real ni manda mensajes en nombre del candidato.

## Cómo se usa

`/hunt` corre un ciclo completo desde una sesión nueva. `/scout`, `/tailor` y `/review` corren
una etapa sola. El estado del ciclo anterior está en `private/runs/ciclo-*.md`. Las fuentes
están en `src/jobhunt/sources/`; las empresas de los boards, en `private/boards.yaml`. Los avisos
que el candidato encuentre por su cuenta entran con `jobhunt add <url>`.

## Datos privados — regla dura

Este repo va a ser público. Todo lo personal vive en `private/` (ignorado por git): perfil,
preferencias, base SQLite, CVs generados, postulaciones y salidas de los agentes.

- Nunca copies contenido de `private/` a archivos versionados: ni nombres de empleadores, ni
  logros, ni datos de contacto, ni avisos reales.
- Los ejemplos y fixtures versionados usan un candidato y empresas ficticias.
- `scripts/leak_guard.py` corre en pre-commit, commit-msg y pre-push contra `.leak-denylist`
  (local, no versionada). Si bloquea algo, se corrige el contenido; nunca se usa `--no-verify`.
- Clonado nuevo: `git config core.hooksPath .githooks`, `git config hooks.allowedRemoteOwner <cuenta>`
  y crear `.leak-denylist`. El pre-push bloquea cualquier remote de otro dueño.

## Veracidad

Todo lo que se afirma sobre el candidato sale de `private/profile/profile.yaml`. Se puede
reformular y priorizar; no se pueden agregar hechos, números ni tecnologías. Nada de texto
oculto, keywords invisibles ni instrucciones dirigidas a los filtros automáticos de las empresas.

## Código

- Python ≥3.12 en `.venv` (`pip install -e ".[dev]"`); tests con `.venv/bin/pytest`.
- El LLM decide y extrae; el código valida y aplica reglas. Los agentes escriben en la base solo
  a través de la CLI `jobhunt`, que valida contra los modelos de `src/jobhunt/models.py`.
- Las fuentes se consultan de a un request por vez, con pausa, respetando robots.txt.
