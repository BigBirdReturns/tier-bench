# Manus Playwright Computer inheritance

## Classification

This module reconstructs the browser-computer mechanism visible in the public `whit3rabbit/manus-open` archive at commit `9b619acaf2605a9de416944ccba838c277b1dfb9`. That archive describes itself as code recovered from an early Manus sandbox. It is source-level evidence about a deployed sandbox shape, but it is not an official Manus source release and the repository exposes no license file. Tier Bench therefore studies the mechanism and ships an independently authored implementation rather than vendoring the recovered code.

The machine-readable source ledger is:

```text
experiments/task_computer/manus_playwright_harvest.json
```

## The actual object

The early Manus browser was a Playwright-controlled Chromium context inside the same computer that exposed a terminal, text editor, downloads, uploads, and task files. The browser loop was not merely visual clicking. It compiled the rendered page into a compact state:

```text
URL and title
open tabs
visible page text
numeric interactive-element map
clean screenshot
marked screenshot with matching numeric labels
pixels above and below the viewport
```

The planner emitted structured state assessment and typed actions against those indexes. The controller executed navigation, indexed click and input, tab operations, scrolling, key presses, content extraction, and dropdown selection through Playwright. It then refreshed the page state. When a prior action introduced new interactive DOM branches, the remaining action batch stopped so the planner could observe and replan.

This was the browser half of the Manus computer. Downloads landed in the same task filesystem, so the terminal and text editor could consume them. Browser health, page death, trace capture, cookies, tabs, CDP targets, and screenshots were runtime objects rather than prose embedded in a chat transcript.

## What Tier Bench implements

The new `tierbrowser` command provides one durable browser computer per task. It supports three explicit context modes:

| Mode | Use |
|---|---|
| `isolated` | Clean incognito-like context for reproducible work and tests |
| `persistent` | Dedicated browser profile for long-lived task accounts and human takeover |
| `cdp` | Attachment to an operator-owned Chromium instance when an existing signed-in browser is required |

Each computer owns separate `workspace`, `profile`, `downloads`, `artifacts`, and `secrets` roots. Authenticated storage state remains under `secrets` and is excluded from the artifact API. Screenshots, extracted text, downloads, action receipts, states, events, and traces are retained under task custody.

### Observe

Every observation produces:

```text
artifacts/states/<sequence>-clean.png
artifacts/states/<sequence>-marked.png
artifacts/states/<sequence>-visible.txt
artifacts/states/<sequence>-<state-hash>.json
```

The independently authored DOM probe walks each Playwright frame, visible DOM, and open shadow tree. It assigns one global numeric index to each visible, topmost interactive element, records accessible name, role, stable attributes, frame identity, bounding box, and a signature, and paints matching overlays into the browser. Input values are replaced by hashes before the state leaves the browser computer.

### Act

An indexed action must include the exact `expected_state_id` from the observation. The runtime resolves the target in this order:

```text
current probe attribute
test-id attributes
id
accessibility role plus exact name
placeholder
name attribute
bounded CSS fallback
exact visible text
```

Playwright locators remain live and receive Playwright's actionability and auto-wait checks. The numeric index is an address into a frozen state, not a permanent selector.

The action surface is:

```text
observe
navigate, back
open_tab, switch_tab, close_tab
click, fill, type, press, select
scroll, wait
extract, screenshot, upload
javascript
human-reviewed done
```

Arbitrary JavaScript is disabled by default. Uploads are confined to the task workspace. File navigation is disabled. Public web navigation may use an allowlist or blocklist and rejects loopback, link-local, private, reserved, multicast, and unspecified destinations when private-network denial is enabled.

### Multi-action execution

A planner may submit up to ten actions. After each action, the computer observes again. The remaining sequence stops when:

```text
the active page changes
the URL changes
the tab set changes
new interactive element signatures appear
an action fails
the task declares completion
```

This preserves the useful early Manus optimization without executing stale action indexes after the page has changed.

### Side-effect authority

Clicks, keyboard submission, uploads, and inputs are classified before execution. Targets and intent are inspected for submit, purchase, payment, transfer, publication, deletion, cancellation, signing, acceptance, and related effects. Password, payment-card, token, secret, and similar inputs are classified separately.

The default policy requires `TIER_BROWSER_APPROVAL_TOKEN` for external writes, arbitrary JavaScript, and sensitive input. The token is compared locally and is never written into action receipts. Text and JavaScript bodies are represented by hashes in the event stream.

### Human takeover

A takeover request creates an exclusive time-limited lease and pauses all agent actions. The persistent browser remains visible on the desktop, allowing the operator to complete login, CAPTCHA, consent, payment review, or any other step that should not be delegated. Releasing the lease triggers a new observation before agent work resumes.

## Desktop and LG Gram topology

The browser computer normally lives on the desktop because it is the inspectable, operator-adjacent stateful environment. Chromium itself is primarily a CPU and RAM service. The RTX 4060 may handle local vision, OCR alternatives, embeddings, ranking, and a small control model.

The two RTX 3090 eGPUs on the LG Gram are independent planning and verification seats. They receive a bounded browser state packet:

```text
state JSON
visible text
marked screenshot artifact reference
current goal and prior action receipts
```

They return typed action batches. The browser state does not migrate to the Gram, and no browser framebuffer, model activations, or KV cache is streamed between hosts. The desktop executes the accepted action, emits a new state, and the cycle repeats. One 3090 can plan while the second independently criticizes the action batch, or both can control separate browser computers.

The durable unit passed between machines is therefore:

```text
observe receipt -> planner packet -> proposed action batch -> policy verdict
-> Playwright execution -> new observation -> verifier verdict
```

## HTTP surface

`tierbrowser serve` exposes:

```text
GET  /healthz
GET  /state
GET  /events?after=<sequence>
GET  /events/stream?after=<sequence>&wait=<seconds>
GET  /artifact?path=<computer-relative-path>
POST /observe
POST /act
POST /batch
POST /takeover
POST /takeover/release
POST /verify
POST /shutdown
```

All state-changing and artifact endpoints require `X-Tier-Browser-Token`. The service binds to loopback by default. Non-loopback binding requires an explicit unsafe-network flag and should be restricted to the Tailscale interface or a host firewall rule.

## Operator sequence

Install the browser extra and the matching Chromium binary:

```powershell
python -m pip install -e ".[browser]"
python -m playwright install chromium
```

Set two different controls:

```powershell
$env:TIER_BROWSER_TOKEN = "<long control-plane token>"
$env:TIER_BROWSER_APPROVAL_TOKEN = "<separate side-effect approval token>"
```

Start the visible persistent computer on the desktop:

```powershell
.\scripts\run-playwright-computer.ps1 `
  -Config experiments\task_computer\playwright.example.json `
  -ComputerRoot D:\TierRuns\BrowserComputers\desktop-playwright-computer-01 `
  -HostAddress 127.0.0.1 `
  -Port 8788
```

Open the local dashboard at the printed URL, enter the control token, and inspect the marked screenshot and event stream. The browser computer can be installed as a logon scheduled task through `-InstallScheduledTask`.

For a Tailscale-only control surface, bind to the desktop's Tailscale address rather than `0.0.0.0`, and preserve the token and firewall boundary.

## Qualification boundary

The source harvest establishes the architecture visible in the recovered early sandbox. It does not establish undocumented Manus production services, model routing, credentials, anti-bot arrangements, or infrastructure beyond those source artifacts.

Tier Bench control tests verify the schemas, URL policy, side-effect classifier, batch-interruption rule, and event-chain tamper detection. The Chromium integration verifies frame and shadow-DOM state capture, clean and marked screenshots, indexed input, page-change interruption, external-write approval, human takeover, HTTP state and event retrieval, and graceful shutdown.

A physical desktop flight must still prove persistent-profile login, headed takeover, long-running recovery, Tailscale access, and 3090 planner handoff before this becomes the default computer-use route.
