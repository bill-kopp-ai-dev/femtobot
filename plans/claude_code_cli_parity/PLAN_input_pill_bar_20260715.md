# Plan: Input Pill Bar (Claude Code v2.1.x parity)

**Scope:** `femtobot/` (canônico em `agents/femtobot`).
**Target release:** `v0.1.0-ui.1` (preview of v0.1.0-ui is already merged in `main` at `bb84621`).
**Profile target:** `ui_parity=compat` (i.e. when `ParityStreamRenderer` is active).
**Auto-fallback:** the bar is suppressed under `off` and `full` — same D2 rules as the rest of the parity layer.
**NOT in scope:** reshaping the input widget itself (textarea styling, multiline UX, history navigation). We just frame the line the user types into.

---

## 1. Background — what the user sees today

Under `ui_parity=compat` after `bb84621`, the REPL prints the legacy `You:` prompt with a Rich `HTML` formatter wrapped in `prompt_toolkit.patch_stdout`. Concretely, [commands.py:554-599](file:///home/bill/Codes/agents/femtobot/femtobot/cli/commands.py#L554-L599):

```python
renderer = _ACTIVE_RENDERER
if renderer is not None:
    try:
        renderer.print_input_gap()
        renderer.print_user_box()
    except Exception:
        pass
# ... lateral margin spacer ...
with patch_stdout():
    return await _PROMPT_SESSION.prompt_async(
        HTML(f"<b fg='ansiblue'>{margin_spaces}You:</b> "),
    )
```

What you actually get on screen:

- A few blank lines + the `[ user_box ]` header (Camada 5 P3 fix).
- The prompt `"You:"` in ansi-blue, followed by typed input.
- Nothing framed — the prompt sits flush on whatever the agent left below it.

## 2. What the user wants (Claude Code v2.1.x reference)

The Claude Code CLI (images 1-4 of the user request) prints **a thin horizontal accent bar** full-width above the input row. While idle, the bar is dim; when the user starts typing, the bar brightens (Rich `Rule`/`Panel`-style). Below the prompt the bar continues as the bottom border. Placeholders appear in dim, the prompt glyph (`>`) is bold and tinted.

Visually the user gets a stable, framed text-entry slot at the bottom of the terminal — exactly like Claude Code, with the same color emphasis that the welcome card uses (`theme.welcome_border`).

## 3. Design constraints (where it has to live)

Three places are involved:

| Layer | Concern | Hook already present? |
| --- | --- | --- |
| `femtobot.cli.parity_widgets` | The pure renderable (top + bottom rule + prompt glyph) | **Partial** — `render_input_pill()` exists at [parity_widgets.py:411](file:///home/bill/Codes/agents/femtobot/femtobot/cli/parity_widgets.py#L411) but is **never called** (an audit comment in the docstring confirms it's frame-only and was never wired). |
| `femtobot.cli.commands._read_interactive_input_async` | Where to print the bar so it survives `prompt_toolkit`'s redraws | **Partially** — `print_input_gap` + `print_user_box` already run *outside* `patch_stdout()`. |
| `femtobot.cli.commands.run_interactive` (REPL loop) | What gets re-printed between turns; idempotency rules | The renderer is now reused across turns (commit `bb84621`) so printing a stable frame is safe. |

**Key constraint:** `prompt_toolkit.patch_stdout()` redraws the prompt area on every key event. Any text printed *inside* that block is captured and re-rendered as part of the prompt's own display, but the **bottom border** must sit *just before* the prompt starts (similar to how `print_input_gap` blanks sit on top today).

**Strategy:** print the bar in two slices:

- **Top bar** — *before* `with patch_stdout()`. Stays sticky on the line above the prompt (already proven to work by `print_input_gap` / `print_user_box`).
- **Bottom bar + prompt glyph** — *inside* the `HTML(...)` template via prompt_toolkit's `HTML` formatter, since they belong to the same logical row. prompt_toolkit re-draws them on every key.

That gives Claude Code's visual: a box carved into the terminal bottom, with the prompt glyph flush-left in accent color.

## 4. What changes

### 4.1 Pure renderable (T1)

Replace the unused `render_input_pill` with a more usable **two-piece** helper:

```python
def render_input_bar_top(*, theme: CliTheme | None = None) -> RenderableType:
    """Thin full-width accent rule printed above the prompt row."""

def render_input_bar_bottom_with_prompt(
    *, prompt: str = ">", placeholder: str = "", theme: CliTheme | None = None
) -> str:
    """Bottom rule + bold prompt glyph as ANSI for prompt_toolkit HTML.
    Returns a string of HTML-escaped markup (no Rich objects).
    """
```

Theme accent: `theme.welcome_border` (already used by the Welcome card → visual coherence).

### 4.2 REPL plumbing (T2)

Extend the protocol in [renderer_factory.py:34-59](file:///home/bill/Codes/agents/femtobot/femtobot/cli/renderer_factory.py#L34-L59) with two methods:

```python
def print_input_bar(self) -> Any: ...          # top bar (full Rich renderable OK)
@property
def input_prompt_markup(self) -> str: ...       # bottom bar + glyph as HTML
```

- `StreamRenderer.print_input_bar` returns a no-op `Console.print` call (the legacy profile keeps the unframed `"You:"` prompt).
- `StreamRenderer.input_prompt_markup` returns the existing `HTML(f"<b fg='ansiblue'>{margin_spaces}You:</b> ")` markup, unchanged.
- `ParityStreamRenderer.print_input_bar` prints the new `render_input_bar_top`.
- `ParityStreamRenderer.input_prompt_markup` returns the new bottom-bar-and-glyph markup.

### 4.3 Reading input (T3)

In `_read_interactive_input_async` ([commands.py:554-599](file:///home/bill/Codes/agents/femtobot/femtobot/cli/commands.py#L554-L599)):

- *Before* `with patch_stdout():`: call `renderer.print_input_bar()` after the existing `print_input_gap` + `print_user_box`.
- *Inside* the `prompt_async(...)` call: pass `renderer.input_prompt_markup` instead of the hard-coded `HTML(...)`.

Replacing `HTML(...)` with a plain `str` (since `prompt_async` accepts a `str | Prompt`) is fine — we want prompt_toolkit to render the entire line including the bottom border.

### 4.4 Suppress the legacy "Manual mode on" (T4)

The bottom row currently prints `▌ manual mode on` via a different code path (the status footer). Under `compat` we want **only** the new bar+glyph combo, so the legacy footer should be skipped when `_resolve_profile(config) == "compat"`. This matches how the legacy "Interactive mode" banner was already suppressed in [commands.py:1276-1280](file:///home/bill/Codes/agents/femtobot/femtobot/cli/commands.py#L1276-L1280).

### 4.5 Slash command toggle (T5 — optional, but cheap)

`/ui` already exists (`md_commands.py`). Add a tiny `/bar` slash that toggles `agents.cli.ui_parity.bar_enabled` (live, in-session). Default `True` under `compat`. When `False`, the bar collapses back to the unframed legacy prompt without dropping to `off`.

### 4.6 Tests (T6)

In `tests/cli/test_parity_widgets.py` (which already covers `render_input_pill`):

- `render_input_bar_top` emits a `Rule`/`Text` whose width matches the console width minus `margin_x`.
- `render_input_bar_bottom_with_prompt` returns ANSI-safe HTML (no Rich escapes), begins with the accent rule, then `>` glyph.
- Snapshot test for parity with Claude Code: capture at width=120 and assert non-empty accent rule spans ≥ 60 chars.

In `tests/cli/test_parity_stream.py`:

- New `def test_parity_renderer_exposes_bar_methods` (mirror of the streamed-property test from commit `f690aac`).
- Mock the protocol: legacy `StreamRenderer` returns no-ops; parity returns the new renderable.

In `tests/cli/test_commands.py` (E2E-ish, optional):

- `await run_interactive`-style test that calls `_read_interactive_input_async` with a fake renderer and asserts both `print_input_bar` and `input_prompt_markup` were reached.

### 4.7 Docs (T7)

- Update `docs/cli-ui-parity.md` with a "Input Pill Bar" section + ASCII sketch.
- Update `docs/cli-reference.md` entry for `femtobot agent --ui compat`.

## 5. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| `prompt_toolkit` redraws the prompt on every key event — bottom bar inside the prompt must redraw cleanly. | Use plain text (no Rich `Console.print`) so prompt_toolkit owns the redraw; assert no ANSI control characters leak into the input field via a unit test that strips ANSI and compares. |
| Existing `render_input_pill` is a dead export — removing it could break imports. | `grep -r 'render_input_pill' .` first; if anything imports it (current scope: nothing), keep a thin re-export. |
| Theme-aware accent must not break in `off` profile. | Gate the entire feature on `_resolve_profile(config) == "compat"`; the protocol methods on legacy `StreamRenderer` are no-ops. |
| Width handling — bar too long truncates, too short looks off. | Use `console.width` (already available in the parity renderer) and clamp to `[60, console.width - margin_x*2]`. |
| `_ACTIVE_RENDERER` lifecycle: when the renderer is `None` (one-shot mode), the bar must still not crash. | `_read_interactive_input_async` early-bails on `renderer is None`, same as today. |
| `print_input_gap` + `print_input_bar` interact — order matters or the bar floats above the gap. | Bar is printed **after** `print_input_gap`, **before** `patch_stdout()`. The gap provides vertical breathing room; the bar is the horizontal frame. |

## 6. Acceptance criteria

1. Under `ui_parity=compat`, `femtobot agent` shows — on the first idle prompt and every prompt thereafter — a thin top accent bar spanning the terminal width above a bold `>` glyph, and a matching bottom bar at the same column. Placeholder text is visible only when the buffer is empty.
2. Under `ui_parity=off`, the prompt collapses back to the legacy `You:` prompt, byte-identical to `bb84621`.
3. The bar survives `prompt_toolkit`'s redraws (typing characters does not chop the bar).
4. `pytest` stays green (1176 tests + new ones from T6).
5. `ruff check` is clean across the touched files.
6. `git push` lands on `origin/main`; `agents/femtobot` and `CLI-router-project/femtobot` stay in sync.

## 7. Task breakdown

- **T1** — rewrite `render_input_pill` as `render_input_bar_top` + `render_input_bar_bottom_with_prompt` in `parity_widgets.py`. Add unit tests in `tests/cli/test_parity_widgets.py`.
- **T2** — extend `RendererLike` protocol in `renderer_factory.py` with `print_input_bar` + `input_prompt_markup`; wire defaults on `StreamRenderer` (no-op + legacy markup); override in `ParityStreamRenderer`.
- **T3** — update `_read_interactive_input_async` in `commands.py` to call `renderer.print_input_bar()` and use `renderer.input_prompt_markup`. Preserve the lateral margin spacer.
- **T4** — suppress the legacy status footer (`▌ manual mode on`) when `_resolve_profile(config) == "compat"`.
- **T5 (optional)** — `/bar` slash in `md_commands.py` toggles `agents.cli.ui_parity.bar_enabled` in-session.
- **T6** — parity_stream tests + (optional) commands E2E test.
- **T7** — docs: `cli-ui-parity.md` + `cli-reference.md`.
- **T8** — validate (ruff + pytest), commit, push, sync `CLI-router-project/femtobot`.

Order: **T1 → T2 → T3 → T4 → T6 → T7 → T8**. T5 can be inserted between T4 and T6.

## 8. Out of scope (deferred)

- Multiline-mode visual differentiation (the bar is single-row even in multiline; multi-row framing requires prompt_toolkit FormattedTextControl hooks, deferred).
- Animated / live-accent border on typing (only Claude Code's "highlight while typing" effect; deferred — keep parity lean).
- `ui_parity=full` (Textual) integration. The Textual TUI draws its own widgets; will reuse `render_input_bar_top` once `full` lands in `v0.1.0-ui.1`.
