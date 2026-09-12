# Seed format

`demo.json` is synthetic workflow data. It has no claimed psychometric validity and cannot be imported in production mode.

Top-level fields are `metadata`, `dimensions`, `rules`, `jobTemplates`, `talentTypes`, `sampleAnswers`, and `questions`. Production content must set `metadata.mode` to `production`, `metadata.expertConfirmed` to `true`, `metadata.synthetic` to `false`, and `rules.demo` to `false` after expert review.

Every question has `id`, `type`, `text`, `required`, `weight`, `reverse`, and non-empty `dimensionIds`. Supported types add these fields:

- `single`: non-empty `options` with `id` and `label`.
- `multiple`: options plus `minSelections` and `maxSelections`.
- `scale`: numeric `min` and `max` where min is less than max.
- `experience`: integer `maxLength`.

The current assessment is fixed at exactly 40 unique questions. Weights are greater than 0 and at most 1. All dimension references must resolve to `dimensions[].id`.

Expert-confirmed production content must also provide a non-empty `rules.scoringAnchors` list. Changing the demo metadata flags alone cannot make the synthetic fixture publishable as production content.

Scoring anchors use unique `id` values and cover every question exactly once through `questionId`; each declares a method and finite ascending score range. Talent types reference existing dimension IDs. Each supplied sample-answer set has a distinct `ownerId` and exactly one answer for every question. Production content rejects `synthetic: true` on anchors, talent types, or job templates.

Each scoring anchor has a unique `id`, a valid `questionId`, a named `method`, and a finite two-number `range`. The demo contains one visibly synthetic anchor per question. `talentTypes` is a synthetic demonstration dictionary. `sampleAnswers` contains two distinct synthetic users and one compatible answer for every question; it must never be treated as respondent evidence.

The MVP scope remains restricted report-understanding chat. Confirmed conversation facts create a new `ProfileSnapshot`; open-ended companionship is outside this seed and MVP scope.

## Official evidence-only questionnaire

`official-questionnaire.json` is generated from the frozen local copy at `sources/题目与AI报告生成规则.md`, section 2.2. Each question preserves `sourceText`, one-based `sourceLine`, the source dimension, evidence rule, and report use. Run `scripts/import_official_questionnaire.py` to regenerate it or pass `--check` to detect drift.

This asset is `mode=evidence_only`, `synthetic=false`, and `scoringStatus=pending_method`. It intentionally contains no weights, numeric scoring anchors, talent-type classifier, job thresholds, or sample user answers because the source says those methods remain incomplete. The generator creates the JSON asset only; it does not publish a database version or change an active pointer.

Questions use `fields` as their answer schema. Simple questions have one single/multiple field. Q25, Q30, Q31, Q36, Q37, Q38, and Q39 preserve their structured or conditional inputs. Q39 text is optional and its audio field remains marked `pending_implementation`.
