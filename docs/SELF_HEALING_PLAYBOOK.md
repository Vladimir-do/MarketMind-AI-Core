# Parser Agent Self-Healing Playbook

Use this playbook when the user reports that the agent, parser, planner,
exporter, context session, tests, or marketplace workflow behaved incorrectly.

This is not model fine-tuning. It is a professional regression-first repair
standard: every fix starts from evidence, is bounded by safety gates, is
verified by measurable signals, and feeds reusable lessons back into the
skillpack.

## Output Contract

A repair request must become:

```text
StructuredTask(
  type=repair_task,
  parameters={
    repair_mode=regression_first,
    failure_area=<area>,
    severity=<critical|high|medium|low>,
    evidence_types=[...],
    blast_radius=<localized|shared>,
    verification_scope=[...],
    safety_gates=[...],
    requires_regression_test=True,
    requires_focused_tests=True,
    requires_full_tests=<bool>,
    requires_live_smoke=<bool>,
    requires_skillpack_update=True
  }
)
```

## Repair Loop

1. Normalize the user report into `repair_task`.
2. Capture a measurable failure signal:
   - failing test;
   - thrown exception or traceback;
   - empty extraction result;
   - wrong `StructuredTask`;
   - wrong `TaskPlan`;
   - wrong `ParseResult`;
   - bad output file;
   - live smoke result with `status`, `latency_ms`, `records`, `warnings`.
   The current session should store this as `LastFailureMemory` with the
   failed task, target URL, error type/text, validation warnings, result
   metrics and created files when available.
3. Classify `failure_area`:
   - `intent`;
   - `parser`;
   - `page_structure`;
   - `network_or_antibot`;
   - `export`;
   - `test`;
   - `unknown`.
4. Assign severity:
   - `critical`: production outage, security/secrets, destructive data risk;
   - `high`: traceback, failing tests, empty extraction on requested data;
   - `medium`: wrong behavior without crash or data-loss evidence;
   - `low`: docs, wording, non-runtime polish.
5. Estimate blast radius:
   - `localized`: one parser/exporter/fixture path;
   - `shared`: intent routing, planner, agent loop, parser contracts, database,
     worker, Telegram, CLI, skillpack, or unknown root cause.
6. Check safety gates before editing:
   - no destructive commands;
   - do not revert unrelated user changes;
   - no secret logging;
   - preserve existing contracts;
   - network smoke needs a safe target or user approval.
7. Add or update a regression test before or together with the fix.
8. Implement the smallest fix at the failing layer.
9. Run focused tests for the changed area.
10. Run the full suite when `blast_radius=shared`.
11. Run a live smoke check only when the bug depends on a real site and it is
    safe to do so.
12. Save the reusable lesson in `project_skills/skills_database.md` and
    `project_skills/skills_index.json`, or create a pending proposal in
    `project_skills/session_updates/`.
13. Run `python project_skills/validate_skills.py` after skillpack edits.

## Last Failure Memory

Short follow-ups such as `agent failed`, `агент ошибся`, or `почини это` must
not start a marketplace search. They should become `repair_task` and inherit
the latest failed task from `ContextSession.last_failure`.

Minimum memory fields:

```text
last_failed_task
last_error_text
last_error_type
last_result_metrics
last_created_files
last_validation_warnings
```

If the latest failed task was scraping and the repair prompt is short or
ambiguous, classify it as `failure_area=parser`, keep the previous URL, attach
the saved validation warnings, and recompute `verification_scope`,
`safety_gates`, `requires_full_tests`, and `requires_live_smoke`.

## Evidence Types

Use stable labels so telemetry and reports can group failures:

```text
traceback
failing_test
empty_extraction
wrong_intent
http_status
bad_output_file
live_smoke
user_report
```

## Verification Matrix

```text
intent/context       -> focused intent tests + full suite
planner/agent_loop   -> planner/loop tests + full suite
parser/page_structure-> parser tests + safe live smoke when URL-dependent
network/antibot      -> strategy tests + telemetry check + safe smoke if allowed
export               -> export tests + schema/content check
skillpack            -> validate_skills.py + relevant focused tests
unknown/shared       -> focused reproduction + full suite
```

## Planner Contract

Repair tasks should plan these skills:

```text
repair.reproduce
repair.classify
repair.regression_test
repair.implement_fix
repair.verify
repair.skillpack_update
quality.self_critic
```

The agent loop strategy is `regression_first_repair`.

## Executor Contract

Telegram/CLI handlers should route `repair_task` to a dedicated repair
executor, not to scraping, add-url, or marketplace search fallbacks.

The minimal repair executor should:

1. Show the structured repair plan.
2. Show a diagnostic report with target URL, last error type/text, validation
   warnings, evidence, severity, blast radius, safety gates and verification
   scope.
3. Suggest focused test files from `failure_area`.
4. Include the skillpack validator in suggested checks.
5. Avoid editing or running network smoke automatically unless the caller
   explicitly enters a repair implementation flow.

## Anti-Patterns

- Treating a bug report as a fresh scraping task.
- Guessing that a fix worked without a measurable signal.
- Hiding missing executors behind a successful-looking plan.
- Fixing prompt text only, without a regression.
- Inventing scraped data when extraction fails.
- Running network/browser smoke checks as mandatory unit tests.
- Reverting unrelated user work.
