# jobhunt

A multi-agent pipeline for my own job search. It finds postings, scores them against my profile,
writes a tailored one-page CV for each one, and prepares each application form for me to review.
**Every claim in the CV and in the form answers has to trace back to a verified fact about me.**
I submit every application myself, by hand.

The interesting part is the CV agent. An LLM that rewrites a CV for each job is easy to build.
The hard part is making sure it doesn't quietly upgrade "used X once" into "expert in X". This
repo treats that as an engineering problem: grounded generation plus deterministic verification,
with the LLM kept away from decisions that code can make.

## Pipeline

```
 job boards ─► listing filter ─► job-scout ─► policy ─► cv-tailor ─► verifier ─► application-reviewer ─► me
 (polite        (title and       (LLM:        (code:    (LLM: CV     (code:      (LLM: semantic audit;     (review
 scraping,      location rules)  extract,     location, citing       IDs,        code: form reading and    and
 ATS fallback)                   score)       salary,   profile      numbers,    answer checks)            submit)
                                              years)    IDs)         skills)
```

| Stage | Who decides | Why |
|---|---|---|
| Listing filter | Code (regex over title and location) | Cheap and predictable. Of 422 postings on the first run, 37 reached the LLM. |
| Extraction and fit score | LLM (`job-scout`, Sonnet) against a versioned rubric | Reading a posting is a language task. Output is a Pydantic-validated JSON. |
| Apply / maybe / skip | Code (`policy.py`) | Hard constraints (city for hybrid roles, remote-from-Argentina, salary floor, max years) must not depend on a model's mood. |
| CV writing | LLM (`cv-tailor`, Opus) | Choosing and phrasing evidence for a specific reader is a writing task. |
| CV verification | Code (`grounding.py`) | It's binary: either the CV is supported by the profile or it isn't. |
| Semantic CV audit | LLM (`application-reviewer`, Opus), separate from the writer | Whether a rephrased bullet overstates its source takes reading. The agent that wrote the CV doesn't audit it. |
| Form reading | Code (`forms.py`): Greenhouse API, Tally's embedded JSON, plain HTML forms | Field lists, types and options are structured data. No browser, nothing submitted. |
| Form answers | LLM drafts, code verifies (`answers.py`) | Every required field answered or explicitly handed to me; options must exist; selected technologies and numbers must be backed by the profile; salary and dates are always my call. |
| Submitting | Me | Not automated, by design. |

## Grounded CV generation

The profile is a YAML file where every achievement has an ID, both language versions, the
evidence behind it, and a `use` flag (`cv`, `interview`, or not usable yet). There are also
explicit lists of things the candidate must never claim, and of past jobs to leave out.

The tailor writes a JSON document in which **every bullet and the summary cite the profile
IDs they come from**. Before any PDF exists, `jobhunt cv render` runs the verifier, and refuses
to render if any check fails:

- cited IDs exist and are allowed in a CV (not interview-only, not unconfirmed);
- each bullet sits under the employer its sources belong to;
- **every number in the text appears in the cited sources** (`4,515` = `4.515` = `4515`);
- every skill exists in the profile, so no new technologies get added;
- headline, education, languages and contact data match the profile;
- facts that need context get it. Example: "3+ years" requires the older job to be listed,
  otherwise the visible dates add up to less;
- no productivity multipliers ("2x faster"), which the profile marks as unsupported;
- the result fits on one page.

What code can't check is whether a rephrased sentence says more than its source ("led" where
the source says "took part in"). The reviewer agent audits each sentence next to its sources
(`jobhunt cv sources`) and sends anything that overstates or adds back to the writer.

### Keyword coverage, without keyword stuffing

`jobhunt cv keywords` compares the posting's terms with the CV, the way a simple ATS would, and
splits them into three groups:

- **present**: already in the CV;
- **missing but supported**: the profile backs it, so the CV must include it;
- **missing gap**: never added, under any name. That's what the interview is for.

On the first run, the base CV already covered every supported keyword. Everything still missing
was a real gap, which is the honest answer, and it shows up in the notes for interview prep.

## Privacy by construction

This repo is public. My real data is not.

- Everything personal (profile, preferences, database, generated CVs, agent outputs) lives in
  `private/`, which is git-ignored.
- `scripts/leak_guard.py` runs on pre-commit, commit-msg and pre-push. It checks staged content,
  paths, commit messages, author identity and, before a push, the entire history against a
  **local, untracked denylist**. The list itself contains the names that must not leak, so it
  can't be committed. If the list is missing, the guard fails closed.
- Pre-push also checks that the remote belongs to an allowed GitHub account.
- Tests and examples use a fictional candidate.

## Scraping etiquette

One request at a time, with a fixed delay and backoff, an honest user agent, and only paths that
robots.txt allows. When an aggregator has no description, the pipeline fetches it from the
company's ATS (BambooHR's public JSON, or plain HTML). On the first run this changed two
verdicts: the aggregator said "remote", but the real posting said hybrid.

## Layout

```
.claude/agents/        job-scout, cv-tailor, application-reviewer
.claude/skills/        /scout, /tailor, /review (orchestration: batches, parallel subagents)
rubrics/               fit.md, cv-tailoring.md, application-review.md
src/jobhunt/
  sources/             one module per job board
  policy.py            deterministic decisions, ATS detection
  models.py            Pydantic contracts for every LLM output
  grounding.py         CV verifier
  keywords.py          ATS-style keyword coverage
  forms.py             application form readers (no submission)
  answers.py           form answer verifier
  cv.py                CV document model and HTML → PDF render (headless Chrome)
  cli.py               the only way agents write to the database
templates/cv.html.j2   single-column CV template
scripts/leak_guard.py  privacy guard
tests/                 pytest
```

Agent prompts and rubrics are in Spanish, my working language. CVs come out in the language of
each posting.

## Usage

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
git config core.hooksPath .githooks
git config hooks.allowedRemoteOwner <your-github-user>
cp examples/preferences.example.yaml private/preferences.yaml   # then edit
# private/profile/profile.yaml: your verified profile
# .leak-denylist: terms that must never be committed

.venv/bin/jobhunt fetch startups_argentina
.venv/bin/jobhunt report
.venv/bin/jobhunt cv render private/applications/<job>/cv.json --out <file>.pdf
.venv/bin/pytest
```

The agents run inside Claude Code through `/scout`, `/tailor` and `/review`.

## Roadmap

- [x] Scout: scraping, listing filter, LLM extraction and scoring, deterministic policy
- [x] Tailor: grounded CV, verifier, keyword coverage, one-page PDF
- [x] Reviewer: semantic CV audit, form extraction, grounded answer drafts, a package ready
      for manual submission
- [ ] Evals: measure the auditor against seeded exaggerations, the scout's extraction against a
      hand-labeled set, and the tailor's rejection rate across prompt versions
- [ ] Ashby and Workable forms (rendered client-side today, marked for manual review)
- [ ] More sources: Get on Board API, public Greenhouse / Lever / Ashby boards
