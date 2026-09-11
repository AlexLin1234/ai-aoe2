# Debug report: strategist returned no validated plan

- **Symptom:** `StructuredAgentClient.request` raised `ValueError: strategist returned no validated plan` on every loop cycle.
- **Root cause:** The configured 300-token response limit included GPT-5 Mini reasoning tokens. A reproduction returned `status=incomplete`, `reason=max_output_tokens`, 256 reasoning tokens, and no parsed output. After raising the limit, the existing API schema exposed a second issue: it allowed parameter combinations that the local `Action` validator rejected, such as `WAIT` with `count=5`.
- **Fix:** Raised the default response limit to 2,048 tokens, added API-facing action variants that encode valid parameter combinations, converted the API result back to the internal `Plan`, and included response status/reason/error in empty-plan exceptions.
- **Evidence:** A text-only API request returned a valid parsed `WAIT` plan. A complete dry-run cycle with screenshot upload disabled captured the AoE2 window, parsed a four-action plan, executed it in dry-run mode, and wrote telemetry. That response used 954 output tokens.
- **Regression test:** `tests/test_client.py` checks the default token budget, incomplete-response diagnostics, and rejection of invalid `WAIT` parameters.
- **Related:** The repository-wide Ruff check still reports pre-existing formatting issues outside this change; Ruff passes on the changed client and regression test.
- **Status:** DONE_WITH_CONCERNS — the screenshot-enabled API path was not run because external image upload requires explicit user approval.
