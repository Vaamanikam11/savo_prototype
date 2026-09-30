# Signal Event demo

A small, working prototype of a **structured narrative interview that produces evidence-backed scores**.
I built it to understand the problem Savo is solving: turning what people say into signals you can defend.
It is my own interpretation of Savo's public description, not a copy of anything internal, and it only uses
synthetic or self-written data.

**Stack:** React + TypeScript, FastAPI, PostgreSQL, Docker Compose, GitHub Actions. Follow-up questions and scoring
use an LLM (OpenAI or Anthropic, chosen by `LLM_PROVIDER`) through forced function calling, so output is
schema-shaped. I ran and evaluated it end to end with OpenAI `gpt-4o-mini`. The Anthropic provider is implemented
but I have not run it against the live API.

**Live demo:** _add link here_ (access code shared separately)

## Run it

```bash
docker compose up --build
# open http://localhost:5173
```

By default it runs in **mock mode**: a keyword heuristic that needs no API key. It exists for tests and CI and is
*not* an AI model. For real scoring:

```bash
cp .env.example .env     # set LLM_PROVIDER=openai and OPENAI_API_KEY (or anthropic + ANTHROPIC_API_KEY)
docker compose --env-file .env up --build
```

If a provider is selected but its key is missing, the backend refuses to start rather than silently falling back.
The results panel always shows which scorer produced the scores.

Without Docker (uses SQLite instead of Postgres):

```bash
# terminal 1
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
export LLM_PROVIDER=openai OPENAI_API_KEY=...   # omit both for mock mode
python -m uvicorn app.main:app --reload

# terminal 2
cd frontend
npm install
npm run dev
```

## Sharing it safely

The API key lives only on the server as an environment variable; the browser never sees it. Because a public link
can be forwarded, the backend also has: an optional `ACCESS_CODE` for starting an interview, per-IP rate limits,
a `MAX_SESSIONS_PER_DAY` cap, and graceful fallback if the model call fails. `GET /api/admin/sessions` (enabled only
when `ADMIN_TOKEN` is set, sent as `X-Admin-Token`) returns stored sessions. Rate limiting is in-memory and
single-instance, which is fine for a demo but not for production. Interview answers are stored in the database.

## How it works

1. **Framework first.** The dimensions and 0-4 behavioural anchors (`backend/app/framework.py`) are fixed before
   the interview starts. Scores are always relative to these, never to whatever the model finds interesting.
2. **Interview.** The participant answers up to five open questions; follow-ups are generated from the transcript.
3. **Scoring.** The model returns one result per dimension: a score (or null) and verbatim quotes.
4. **Grounding check** (`backend/app/grounding.py`). Every quote must be found in a *participant* turn
   (whitespace and case tolerant). Quotes that are not found are dropped. A dimension left with no grounded
   evidence becomes `insufficient_evidence` instead of a score.
5. **Results view.** Each score sits next to the exact words behind it; selecting a quote highlights it in
   the transcript.

The design choice I care most about: the system prefers saying "not enough evidence" to producing a plausible score.

## Evals

`backend/evals/` holds five synthetic transcripts, including vague answers and "I am very adaptable" self-description
with no behaviour, which must *not* earn behavioural scores.

```bash
cd backend
python -m evals.run_evals                                                 # mock
LLM_PROVIDER=openai OPENAI_API_KEY=... python -m evals.run_evals --runs 3 # real model
```

Metrics: groundedness (quotes kept / proposed), abstention, coverage, and run-to-run consistency.

### What the real-model evals showed (gpt-4o-mini, 3 runs per case)

| | v1 prompt | v2 prompt |
|---|---|---|
| groundedness (quotes kept / proposed) | 100% (66/66) | 100% (34/34) |
| abstention | 58% (7/12) | 83% (10/12) |
| coverage | 100% (6/6) | 100% (6/6) |
| run-to-run consistency | 85% (17/20) | 95% (19/20) |

v1 never fabricated a quote, but it scored five dimensions it should have left empty. Reading the failures:

- **My scale conflated "low" with "no evidence".** The reflection anchor for 0 was "No reflection offered", so the
  model scored 0 on vague answers, following my framework literally. Fix: a 0 now requires *described* low
  behaviour; silence must be `null`. The reflection 0 anchor was reworded accordingly.
- **The model credited self-claims** ("I just roll with whatever comes") as behaviour. Fix: the prompt now says
  trait claims are not evidence.
- **The grounding check cannot catch either problem.** It proves a quote exists in the transcript, not that the
  quote supports the score. Groundedness at 100% only rules out fabrication. Checking that evidence is *relevant*
  to the dimension needs a second pass (for example an entailment check) or human-labelled data.
- Scores moved between identical runs even at temperature 0, so any real use would need repeated scoring or
  agreement thresholds.

v2 improved abstention from 58% to 83% and consistency from 85% to 95%, with no fabricated quotes. Two failures
remain: the model still scores `response_to_change=0` on vague replies ("it was fine"), and gives
`learning_agility=2` to a story that never mentions learning. The model also proposed fewer quotes overall in v2
(34 vs 66), which is part of why abstention improved.

**Limits, stated plainly:** five cases and three runs is a small sample, so I treat these numbers as directional,
not as validation. I stopped tuning the prompt after v2 on purpose, because further changes would risk fitting it
to these five cases. The mock is a keyword heuristic, so its eval numbers only show that the pipeline and the
grounding guardrail work, not that scoring is valid.

## Tests

`pytest` covers the grounding logic (fabricated quotes, interviewer text, whitespace, abstention), the full API
flow, the guardrails, model-outage handling, and the OpenAI provider (against a fake client). CI runs tests, evals
(mock) and the frontend build.

## What I would do next

- **Voice:** replace the text composer with a LiveKit agent; transcripts would feed the same turn pipeline.
- **Better measurement:** a relevance/entailment check on each quote, anchored examples per score level,
  agreement against human-labelled scores, and tracking score drift across model and prompt versions.
- **Interviewer quality:** eval follow-up questions for neutrality. Some generated follow-ups are compound or
  echo the participant's own wording.
- **Production basics:** auth, migrations (Alembic), retries and timeouts on model calls, tracing of prompts and
  outputs per session, and shared rate limiting (Redis).

## Built with AI tools

I built this with Claude as a coding assistant, and I want to be specific about who did what. Claude generated the
initial scaffolding: the FastAPI and React code, the database models, and the first version of the eval harness.
I ran it locally, fixed setup problems along the way (for example a proxy issue on macOS that stopped the
frontend from reaching the backend), moved it from the offline mock to the OpenAI API, and ran the evals against the
real model myself.

The first real-model run scored only 58% on abstention. That was the most useful result in the project: it showed a
flaw in how the scale was defined and in the prompt, and it showed that the grounding check does not protect
against it. I changed the anchors and scoring rules and reran, and the table above shows both runs.

What I have not done: validate the scoring against human-labelled data, or test the Anthropic provider against the
live API. The mock mode and the grounding logic are covered by automated tests; the model's scoring quality is only
as verified as the eval results above.