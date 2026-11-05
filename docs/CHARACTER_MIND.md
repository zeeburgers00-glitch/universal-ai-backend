# Character, mood and the self layer

Three modules, one idea: an assistant should be *someone* in style and *measurable* in
claims. Nothing here fakes inner life — the honesty note below is in every response.

| Module | Question it answers | Storage |
|---|---|---|
| `app/character.py` | Who is it, and how does it speak? | `character.json` |
| `app/affect.py` | What mood is it in right now? | `affect.db` (state + event log) |
| `app/mind.py` | What does it know about itself, and what is it fixing? | `mind.db` |

## Character

Four presets, each a different way of talking — not a different set of facts:

| Preset | Voice | Address |
|---|---|---|
| `jarvis` | terse, dry, numbers over adjectives | "Sir" |
| `mentor` | patient, explains the why, ends with one next step | "beta" |
| `friend` | warm, Hinglish-first, teases a little, still honest | "yaar" |
| `analyst` | bullets, quantified uncertainty, assumptions stated | "you" |

Five traits (0–1) plus curiosity: `warmth`, `humour`, `directness`, `formality`,
`verbosity`. They are converted into prompt bands, not numbers the model has to interpret.

```bash
curl -X POST localhost:8000/v1/character/preset -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"preset":"friend","name":"Nova"}'

curl -X PUT localhost:8000/v1/character -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"traits":{"warmth":0.8,"directness":0.9},"language":"hi","tone_rules":["Hinglish first"]}'
```

`GET /v1/character` returns the exact `prompt_block` the brain receives, so you can see
what changed instead of guessing.

## Mood

Five numbers, moved by events and decayed toward baseline on a half-life:

| Value | Range | Half-life | Moved by |
|---|---|---|---|
| valence | -1…1 | 5 h | praise, thanks, insult, success, failure |
| arousal | 0…1 | 1.5 h | frustration, novelty, jokes |
| energy | 0…1 | 3 h | success, failure, long sessions |
| trust | 0…1 | 40 h | praise, insult, thanks |
| curiosity | 0…1 | 2.5 h | novel topics |

Events are read from the message with a keyword lexicon (Hinglish included: "bakwas",
"zabardast", "phir se nahi ho raha") **and** from outcomes: a failed tool counts, a
successful one counts. Talking alone never fakes a success.

The mood only changes *tone*: low energy shortens answers, high arousal calms the delivery
down, low valence asks for softness without performative sadness, low trust demands explicit
verification. It cannot override facts — a missing dependency is reported the same way in
every mood.

```bash
curl localhost:8000/v1/affect -H "X-API-Key: $KEY"
curl -X POST localhost:8000/v1/affect/touch -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"event":"praise","weight":1.0}'
```

`UAI_AFFECT_DISABLED=1` pins everything to baseline if you want a flat, professional voice.

## Self layer

**Self-model** (`GET /v1/mind/self`) is measured, not asserted: agents that exist, belt
tools ready *on this machine*, model configured or not, facts remembered, success rate,
tools per turn, model share, and a `known_gaps` list built from real failures.

**Reflection** (`POST /v1/mind/reflect`) reads the last N turns and looks for four things:

1. a dependency that keeps appearing in errors (`unavailable: pip install X` × N)
2. messages it could not classify (→ add intents, or rely on the model)
3. a belt thinner than the catalogue (→ install, then `/v1/belt/refresh`)
4. too little tool use or too little model use (→ behaviour change)

Each finding becomes a **lesson** (a fact about itself) and, when actionable, a
**proposal**. Reflection also runs on its own every `UAI_REFLECT_EVERY` turns (default 25)
and writes a journal line.

```bash
curl -X POST localhost:8000/v1/mind/reflect -H "X-API-Key: $KEY"
curl localhost:8000/v1/mind/proposals -H "X-API-Key: $KEY"
curl -X POST localhost:8000/v1/mind/proposals/1/decide -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"status":"accepted","note":"installing tonight"}'
```

### The line that is not crossed

`decide` records a decision. It returns `{"applied_by_me": false}` and the exact next step,
because an assistant that silently rewrites its own code is a liability. Self-improvement
here means: **notice the pattern, write it down, propose the fix, let the human apply it,
and prove the fix with a test.**

## Honest limits

- The mood is a five-number state machine. It does not feel anything, and no response says
  it does.
- Personality presets change tone, never beliefs or facts.
- Reflection is pattern matching over its own logs. It finds real problems; it does not
  invent insights.
- Without a model, "self-improvement" is limited to the four checks above — useful, and
  less than it sounds.
