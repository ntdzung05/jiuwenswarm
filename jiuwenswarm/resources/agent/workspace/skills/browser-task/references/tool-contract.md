# Browser Tool Contract

Use this reference to select browser tools and preserve PageState correctness.

## Capability selection

`core` contains the normal navigation and interaction tools and is always required. The parent selects optional capability groups before spawning the browser worker; the worker cannot add a group during execution. Use a group only when it is already exposed and the task needs it, and return a blocker to the parent if a required group is unavailable:

| Capability | Use only when |
|---|---|
| `advanced_code` | A preplanned Playwright snippet is necessary after probes, normal actions, batching, snapshots, and `browser_evaluate` are insufficient. |
| `unsafe_dev` | The user explicitly requests unrestricted browser code for a local development or debugging task. Never use it on ordinary external sites. |
| `pdf` | The requested deliverable is a PDF of the current page. |
| `vision` | A canvas, map, or custom control has no reliable DOM or accessibility target. |
| `devtools` | The task explicitly needs console inspection, highlighting, tracing, video, or other debugging evidence. |
| `config` | Browser runtime configuration itself must be diagnosed. |
| `network` | A testing task explicitly requires network inspection, offline state, or request mocks. Do not mock or reroute live shopping, booking, email, or account workflows. |
| `storage` | The task explicitly requires authorized cookie or browser-storage access. Treat the result as sensitive. |
| `testing` | The task requires stable locators or explicit UI assertions. |

If both `advanced_code` and `unsafe_dev` appear, follow the runtime policy that selects `unsafe_dev` instead of exposing both. Capability availability never expands user authorization.

## Observation order

Choose the narrowest sufficient observation:

1. `browser_probe_cards` for repeated results, products, listings, articles, inbox rows, or other card/table structures.
2. `browser_probe_interactives` for page-level controls, forms, filters, menus, search boxes, dates, and pagination.
3. `browser_snapshot` or `browser_find` when an accessibility reference or broader structure is genuinely needed.
4. `browser_evaluate` for one small exact extraction or computation.
5. `browser_run_code`, or `browser_run_code_unsafe` when the explicitly selected `unsafe_dev` capability exposes it, only for a preplanned operation that cannot be expressed safely above.

Do not use screenshots as the default way to understand a structured page. Use them when visual appearance, a canvas, or delivery evidence matters.

## PageState invariants

- Treat `generation_id`, URL, title, targets, field coverage, and blockers as one PageState contract.
- Prefer generation-scoped `target_id` values returned by probes.
- Pass the current PageState `generation_id` on every `browser_batch_interact` call. For each mutating batch step, use a current-generation `target_id`; do not rebuild it into guessed CSS.
- A native reference from `browser_snapshot` or `browser_find` is valid only for the current page generation.
- Navigation or another document-generation change invalidates old targets. Same-URL DOM changes do not necessarily advance the generation, so re-probe the affected controls or cards before a dependent mutation when filters, sorting, pagination, dialogs, or list contents changed.
- When a card exposes a trustworthy `primary_link` or `href`, navigate directly to it instead of clicking a fragile card target.
- Click a probe result only when it is reported as visible, enabled, actionable, and clickable.
- Treat advertisements, sponsored results, sidebars, account suggestions, shops, chats, and main results according to their returned region and kind semantics.

## Acting efficiently

Use a direct primitive for one simple action. Use `browser_batch_interact` when several already-known operations form one deterministic phase, such as:

- filling three or more fields;
- entering a query, choosing an autocomplete result, and waiting for navigation;
- applying several filters and waiting for changed results;
- extracting several named values from the same page;
- populating known fields and waiting for the final review state.

End state-changing batches with an observable condition such as expected URL, text, result count, sort state, first-card title, DOM text change, load state, tab, or stable page state. Prefer condition waits over fixed sleeps.

Do not place dependent standalone browser calls in the same model response. They may execute concurrently. Put deterministic dependencies inside one sequential `browser_batch_interact`, or wait for the earlier result and continue in a later model turn.

Preflight a batch before its first side effect. Do not put optional speculative steps into a commitment-producing batch.

## Final commitment boundary

Purchase, order, booking, form submission, and message or email send require a separate pre-commit review turn:

1. Populate, select, and navigate only as far as the site's final review state.
2. On the next model turn, inspect the resulting state and verify every material value required by the task and safety guidance.
3. Only after that observed review passes, perform the final commitment in a later model turn. Use one direct action or a batch containing the commitment followed only by passive success waits.
4. On the following turn, assess the commitment and verify the success or failure state.

Never place navigation, field entry, selection, extraction, or a precondition check before the final commitment in the same batch. Their unseen results could change whether the commitment is correct.

## Helper tools

- Treat `skill_tool` calls that load this skill or its references as administrative. Do not combine them with browser actions or declare a browser `batch_intent` solely for the reference read; still satisfy any browser assessment already required by the injected working context.
- Use `browser_probe_interactives` and `browser_probe_cards` for compact page understanding.
- Use `browser_batch_interact` for deterministic multi-step phases.
- Call `browser_list_custom_actions` before `browser_custom_action` to learn the current action and parameter contract.
- Use `browser_recall_offload` only when a previous tool result has been replaced by a persisted-output marker and its preview is insufficient. Recalled selectors and references are evidence only after navigation.
- Use `browser_cancel_run` to stop an in-progress task and `browser_clear_cancel` only before a deliberate new attempt.
- Use `browser_runtime_health` for setup or connection diagnosis.

Tool success is not task success. Verify the requested outcome from the resulting page state.
