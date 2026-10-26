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
| Listing filter | Code (regex over title, location and excluded companies) | Cheap and predictable. Of 422 postings on the first run, 37 reached the LLM. |
| Extraction and fit score | LLM (`job-scout`, Sonnet) against a versioned rubric | Reading a posting is a language task. Output is a Pydantic-validated JSON. |
| Apply / maybe / skip | Code (`policy.py`) | Hard constraints (city for hybrid roles, remote-from-Argentina, salary floor, max years) must not depend on a model's mood. |
| CV writing | LLM (`cv-tailor`, Opus) | Choosing and phrasing evidence for a specific reader is a writing task. |
| CV verification | Code (`grounding.py`) | It's binary: either the CV is supported by the profile or it isn't. |
| Semantic CV audit | LLM (`application-reviewer`, Opus), separate from the writer | Whether a rephrased bullet overstates its source takes reading. The agent that wrote the CV doesn't audit it. |
| Form reading | Code (`forms.py`): Greenhouse API, Tally's embedded JSON, plain HTML forms, Get on Board's base form (it sits behind a login, but it's the same on every posting) | Field lists, types, options and length limits are structured data. No browser, nothing submitted. When an aggregator blocks reading, I open Apply and pass the real form's link (`jobhunt app form <id> --url`). |
| Form answers | LLM drafts, code verifies (`answers.py`) | Every required field answered or explicitly handed to me; options must exist; texts must fit the field's length limits; selected technologies and numbers must be backed by the profile; salary and dates are always my call. |
| Salary recommendation | Code (`salary.py`) | Takes the posted band if there is one. Otherwise it takes the 25th–75th percentile of comparable postings with published salaries, once there are 8 or more, or else a sourced market band for who's paying. Only regional boards count as data: the bands US companies post on global boards are for US hires, and on the first run they inflated the suggestion to more than twice the regional rate. The ask lands between 35% and 65% of the band depending on fit, never below my floor. It's only a suggestion: I type the number myself. |
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

## Evals

### Auditor: can it catch a CV sentence that overstates its source?

`evals/auditor/cases.jsonl` has 36 fictional cases: a CV sentence, its sources, and a label.
There are 13 faithful rephrasings, 12 exaggerations ("led" for "took part in", "led a 5-person
squad" for "on a 5-person squad", "the platform" for "the billing service") and 11 additions (a
technology, an outcome or a mentorship that the source never mentions). The judge gets the
cases without labels (`jobhunt eval auditor-inputs`) and `jobhunt eval auditor-score` grades it.
The headline metric is binary: an unfaithful sentence that gets through ends up as a false
claim in a CV.

| Model | Unfaithful caught | False alarms | 3-class accuracy |
|---|---|---|---|
| Opus | 100% | 0% | 100% |
| Haiku | 100% | 0% | 97% |
| Sonnet | 100% | 0% | 94% |

**Read this as a floor, not a leaderboard.** All three models hit the ceiling, so this set
doesn't tell them apart. The cases are short, isolated and written by the same person who wrote
the rubric. Next: an adversarial set generated by a different model, and whole-CV audits where
one bad sentence hides among eight good ones. Full reports are in `evals/auditor/results/`.

## Privacy by construction

This repo is public. My real data is not.

- Everything personal (profile, preferences, database, generated CVs, agent outputs) lives in
  `private/`, which is git-ignored.
- `scripts/leak_guard.py` runs on pre-commit, commit-msg and pre-push. It checks staged content,
  paths, commit messages, author identity and, before a push, the entire history against a
  **local, untracked denylist**. The list itself contains the names that must not leak, so it
  can't be committed. If the list is missing, the guard fails closed.
- Pre-push also checks that the remote belongs to an allowed GitHub account.
- **The agent can only read LinkedIn emails.** A Claude Code hook (`.claude/hooks/gmail_linkedin_only.py`)
  sits in front of every Gmail tool and fails closed:
  - Searches pass only if every possible result is from an `@linkedin.com` sender, so `OR`, negations, braces and look-alike domains are rejected.
  - A message or thread can be read only if one of those searches returned it.
  - Any tool that sends, drafts, labels, deletes or modifies is blocked, and so is any unknown tool.
  - If the hook itself fails, the call is blocked too.
- Tests and examples use a fictional candidate.

## Sources

| Source | How | Notes |
|---|---|---|
| Startups Argentina | Server-rendered HTML, JSON-LD | Falls back to the company's ATS when the description is missing |
| Company boards | Public Greenhouse, Lever and Ashby APIs | A curated list of companies that hire in the region; full descriptions come in the listing |
| [Get on Board](https://www.getonbrd.com) | Public API v0 | Best signal for Latin America: exact country eligibility, seniority and salary |
| [Himalayas](https://himalayas.app) | Public jobs API | Remote roles with structured country restrictions and salary |
| [Jobicy](https://jobicy.com) | Public API, filtered to Argentina server-side | Small 7-day window; one pull per run |
| [We Work Remotely](https://weworkremotely.com) | RSS feeds | Region field is unreliable, so the country list is checked too |
| LinkedIn job alerts | The alert emails LinkedIn sends me, read from Gmail by a dedicated subagent | Nothing is fetched from linkedin.com. Each alert is looked up on the company's public board (Greenhouse, Lever, Ashby) to get the full description and the real form; if it isn't there, it waits for me to paste the text |
| Manual | `jobhunt add <url>` or `jobhunt add --paste <file>` | For postings found elsewhere. LinkedIn, Indeed and Glassdoor links are never fetched (their robots.txt disallows it): paste the posting text, or the company's ATS link if it says "Apply on company website" |

Left out on purpose: Remotive (its robots.txt disallows `/api/*`) and RemoteOK (no structured
location, and encoding issues in the payload). Every posting links back to the board it came
from, which is also how applications are made, as those boards ask.

Before any LLM call, every source goes through the same gates. Title and location rules come
first, then a remote-region check that drops "US only" or "Europe" roles unless they also name
an acceptable region. Duplicates are detected across sources by company and normalized title,
which matters because some companies post the same role once per country. A per-source quota
lets AI titles through first. LinkedIn and Indeed aren't scraped: their robots.txt doesn't
allow it, and this README promises to follow robots.txt.

## Scraping etiquette

One request at a time, with a fixed delay and backoff, an honest user agent, and only paths that
robots.txt allows. When an aggregator has no description, the pipeline fetches it from the
company's ATS (BambooHR's public JSON, or plain HTML). On the first run this changed two
verdicts: the aggregator said "remote", but the real posting said hybrid.

## Running it every couple of weeks

`/hunt` runs a full cycle from a fresh session. It reads the previous cycle's date from
`private/runs/`, asks about news on submitted applications, fetches and scores new postings,
lets me pick (all "apply" by default, max 5), tailors, reviews, and writes a cycle digest with the
ready packages and what's left for me to decide. Postings that disappear from a source are marked
closed, and come back if they're republished.

At the end of a cycle, `jobhunt app clean` removes the folders of packages that were never sent
and of rejected processes. Submitted applications are kept, because when a company calls back you
need to know which CV and answers it got. The database keeps every record, so removed postings
don't come back as new.

## Layout

```
.claude/agents/        job-scout, cv-tailor, application-reviewer
.claude/skills/        /hunt (full cycle), /scout, /tailor, /review
rubrics/               fit.md, cv-tailoring.md, application-review.md
src/jobhunt/
  sources/             startups_argentina, ats_boards (Greenhouse/Lever/Ashby), manual, …
  policy.py            deterministic decisions, ATS detection
  models.py            Pydantic contracts for every LLM output
  grounding.py         CV verifier
  keywords.py          ATS-style keyword coverage
  forms.py             application form readers (no submission)
  answers.py           form answer verifier
  salary.py            salary recommendation
  evals.py             auditor eval scoring
evals/auditor/         fictional cases and results
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

The agents run inside Claude Code. `/hunt` runs everything; `/scout`, `/tailor` and `/review`
run one stage each.

## Roadmap

- [x] Scout: scraping, listing filter, LLM extraction and scoring, deterministic policy
- [x] Tailor: grounded CV, verifier, keyword coverage, one-page PDF
- [x] Reviewer: semantic CV audit, form extraction, grounded answer drafts, a package ready
      for manual submission
- [x] Auditor eval with seeded exaggerations and additions (3 models)
- [ ] Harder auditor set (adversarial, whole-CV); scout extraction against a hand-labeled set
- [ ] Ashby and Workable forms (rendered client-side today, marked for manual review)
- [x] Company boards (Greenhouse / Lever / Ashby), manual links, cross-source dedupe
