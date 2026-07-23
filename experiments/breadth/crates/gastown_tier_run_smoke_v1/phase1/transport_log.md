# Phase 1 transport log — gastown_tier_run_smoke_v1

Workspace: S:/Temp/claude/gt-phase1/
Binaries: gt v1.2.1 (D:/Tools/gastown-1.2.1/gt.exe), bd v1.1.0 (D:/Tools/beads-1.1.0/bd.exe)
Rule enforced throughout: never run `gt up`. Any tmux/daemon prompt = record DAEMON-REQUIRED and stop.
Custom agent command under test: `python <abs>/capture_fixture.py` with env `TIER_CAPTURE_OUT` set.
Verify launched command line never contains `--dangerously-skip-permissions` (custody fact 3 / PHASE0 finding).

---

## Command: gt sling --help
Sling work onto an agent's hook and start working immediately.

This is THE command for assigning work in Gas Town. It handles:
  - Existing agents (mayor, crew, witness, refinery)
  - Auto-spawning polecats when target is a rig
  - Dispatching to dogs (Deacon's helper workers)
  - Formula instantiation and wisp creation
  - Auto-convoy creation for dashboard visibility

Auto-Convoy:
  When slinging a single issue (not a formula), sling automatically creates
  a convoy to track the work unless --no-convoy is specified. This ensures
  all work appears in 'gt convoy list', even "swarm of one" assignments.

  gt sling gt-abc gastown              # Creates "Work: <issue-title>" convoy
  gt sling gt-abc gastown --no-convoy  # Skip auto-convoy creation

Merge Strategy (--merge):
  Controls how completed work lands. Stored on the auto-convoy.
  gt sling gt-abc gastown --merge=direct  # Push branch directly to main
  gt sling gt-abc gastown --merge=mr      # Merge queue (default)
  gt sling gt-abc gastown --merge=local   # Keep on feature branch

Target Resolution:
  gt sling gt-abc                       # Self (current agent)
  gt sling gt-abc crew                  # Crew worker in current rig
  gt sling gp-abc greenplace               # Auto-spawn polecat in rig
  gt sling gt-abc greenplace/Toast         # Specific polecat
  gt sling gt-abc gastown --crew mel    # Crew member mel in gastown
  gt sling gt-abc mayor                 # Mayor
  gt sling gt-abc deacon/dogs           # Auto-dispatch to idle dog
  gt sling gt-abc deacon/dogs/alpha     # Specific dog

Spawning Options (when target is a rig):
  gt sling gp-abc greenplace --create               # Create polecat if missing
  gt sling gp-abc greenplace --force                # Ignore unread mail
  gt sling gp-abc greenplace --account work         # Use specific Claude account

Natural Language Args:
  gt sling gt-abc --args "patch release"
  gt sling code-review --args "focus on security"

The --args string is stored in the bead and shown via gt prime. Since the
executor is an LLM, it interprets these instructions naturally.

Stdin Mode (for shell-quoting-safe multi-line content):
  echo "review for security issues" | gt sling gt-abc gastown --stdin
  gt sling gt-abc gastown --stdin <<'EOF'
  Focus on:
  1. SQL injection in query builders
  2. XSS in template rendering
  EOF

  # With --args on CLI, stdin goes to --message:
  echo "Extra context here" | gt sling gt-abc gastown --args "patch release" --stdin

Formula Slinging:
  gt sling mol-release mayor/           # Cook + wisp + attach + nudge
  gt sling towers-of-hanoi --var disks=3

Formula-on-Bead (--on flag):
  gt sling mol-review --on gt-abc       # Apply formula to existing work
  gt sling shiny --on gt-abc crew       # Apply formula, sling to crew

Compare:
  gt hook <bead>      # Just attach (no action)
  gt sling <bead>     # Attach + start now (keep context)
  gt handoff <bead>   # Attach + restart (fresh context)

The propulsion principle: if it's on your hook, YOU RUN IT.

Batch Slinging:
  gt sling gt-abc gt-def gt-ghi gastown   # Sling multiple beads to a rig
  gt sling gt-abc gt-def gastown --max-concurrent 3  # Spawn 3 at a time

  When multiple beads are provided with a rig target, each bead gets its own
  polecat. This parallelizes work dispatch without running gt sling N times.
  Use --max-concurrent to throttle spawn rate and prevent Dolt server overload.

Usage:
  gt sling <bead-or-formula> [target] [flags]
  gt sling [command]

Available Commands:
  respawn-reset Reset the respawn counter for a bead

Flags:
      --account string       Claude Code account handle to use
      --agent string         Override agent/runtime for this sling (e.g., claude, gemini, codex, or custom alias)
  -a, --args string          Natural language instructions for the executor (e.g., 'patch release')
      --base-branch string   Override base branch for polecat worktree (e.g., 'develop', 'release/v2')
      --branch string        Resume work on an existing branch instead of creating a fresh polecat branch (use to fix an existing PR)
      --create               Create polecat if it doesn't exist
      --crew string          Target a crew member in the specified rig (e.g., --crew mel with target gastown → gastown/crew/mel)
  -n, --dry-run              Show what would be done
      --force                Force spawn even if polecat has unread mail
      --formula string       Formula to apply (default: mol-polecat-work for polecat targets)
  -h, --help                 help for sling
      --hook-raw-bead        Hook raw bead without default formula (expert mode)
      --max-concurrent int   Throttle spawn rate: spawn N polecats, pause, then spawn N more (0 = no throttle). Does not limit total concurrent polecats
      --merge string         Merge strategy: direct (push to main), mr (merge queue, default), local (keep on branch)
  -m, --message string       Context message for the work
      --no-boot              Skip rig boot after polecat spawn (avoids witness/refinery lock contention)
      --no-convoy            Skip auto-convoy creation for single-issue sling
      --no-merge             Skip merge queue on completion (keep work on feature branch for review)
      --on string            Apply formula to existing bead (implies wisp scaffolding)
      --owned                Mark auto-convoy as caller-managed lifecycle (no automatic witness/refinery registration)
      --pr int               Resume work on the head branch of an existing PR (resolved via 'gh pr view'). Mutually exclusive with --branch.
      --ralph                Enable Ralph Wiggum loop mode (fresh context per step, for multi-step workflows)
      --review-only          Mark work as review-only: assignee evaluates and reports back, must NOT merge/commit/push
      --stdin                Read --message and/or --args from stdin (avoids shell quoting issues)
  -s, --subject string       Context subject for the work
      --var stringArray      Formula variable (key=value), can be repeated

Use "gt sling [command] --help" for more information about a command.

## Command: gt assign --help
Create a new bead and immediately hook it to a crew member.

This is a shortcut for "bd create" + "gt hook". The crew member name
is short-form (just the name), and the rig is resolved in order:
--rig flag, current directory, or by scanning all rigs for the crew
member name. This means "gt assign dave ..." works from anywhere in
the town if dave exists in exactly one rig.

The crew member must exist (the directory <rig>/crew/<name> must be
present) or the command will error.

Examples:
  gt assign monet "Fix the auth token refresh bug"
  gt assign monet "Review error handling" -d "The retry logic looks wrong"
  gt assign monet "Fix auth bug" --type bug --priority 1
  gt assign monet "Fix auth bug" --nudge
  gt assign monet "Fix auth bug" --label important
  gt assign monet "Fix auth bug" --rig beads   # Explicit rig override

Usage:
  gt assign <crew-member> <title> [flags]

Flags:
  -d, --description string   Bead description
  -n, --dry-run              Show what would happen
      --force                Replace existing hooked work
  -h, --help                 help for assign
  -l, --label stringArray    Labels (repeatable)
      --nudge                Wake the agent after hooking
  -p, --priority string      Priority 0-4 (default "2")
      --rig string           Override rig inference
  -t, --type string          Bead type (default "task")

## Command: gt formula --help
Manage workflow formulas - reusable molecule templates.

Formulas are TOML/JSON files that define workflows with steps, variables,
and composition rules. They can be "poured" to create molecules or "wisped"
for ephemeral patrol cycles.

Commands:
  list    List available formulas from all search paths
  show    Display formula details (steps, variables, composition)
  run     Execute a formula (pour and dispatch)
  create  Create a new formula template

Search paths (in order):
  1. .beads/formulas/ (project)
  2. ~/.beads/formulas/ (user)
  3. $GT_ROOT/.beads/formulas/ (orchestrator)

Examples:
  gt formula list                    # List all formulas
  gt formula show shiny              # Show formula details
  gt formula run shiny --pr=123      # Run formula on PR #123
  gt formula create my-workflow      # Create new formula template

Usage:
  gt formula [flags]
  gt formula [command]

Aliases:
  formula, formulas

Available Commands:
  create      Create a new formula template
  list        List available formulas
  overlay     Manage formula overlays
  run         Execute a formula
  show        Display formula details

Flags:
  -h, --help   help for formula

Use "gt formula [command] --help" for more information about a command.

## Command: gt config --help
Manage Gas Town configuration settings.

This command allows you to view and modify configuration settings
for your Gas Town workspace, including agent aliases and defaults.

Commands:
  gt config agent list              List all agents (built-in and custom)
  gt config agent get <name>         Show agent configuration
  gt config agent set <name> <cmd>   Set custom agent command
  gt config agent remove <name>      Remove custom agent
  gt config default-agent [name]     Get or set default agent
  gt config default-agent list       List available agents

Usage:
  gt config [flags]
  gt config [command]

Available Commands:
  agent              Manage agent configuration
  agent-email-domain Get or set agent email domain
  cost-tier          Get or set cost optimization tier
  default-agent      Get or set default agent
  get                Get a configuration value
  set                Set a configuration value

Flags:
  -h, --help   help for config

Use "gt config [command] --help" for more information about a command.

## Command: gt config agent --help
Manage per-agent configuration settings.

Subcommands allow listing, getting, setting, and removing agent-specific
config values such as the default AI model or provider.

Usage:
  gt config agent [flags]
  gt config agent [command]

Available Commands:
  get         Show agent configuration
  list        List all agents
  remove      Remove custom agent
  set         Set custom agent command

Flags:
  -h, --help   help for agent

Use "gt config agent [command] --help" for more information about a command.
## Command: gt config agent set --help
Set a custom agent command in town settings.

This creates or updates a custom agent definition that overrides
or extends the built-in presets. The custom agent will be available
to all rigs in the town.

The command can include arguments. Use quotes if the command or
arguments contain spaces.

The provider preset is inferred from the command binary name when it
matches a known preset (e.g., "gemini", "claude"). Use --provider to
set it explicitly for custom binary names. The provider controls
session handling, tmux detection, hooks, and other runtime defaults.

Examples:
  gt config agent set claude-glm \"claude-glm --model glm-4\"
  gt config agent set gemini-custom gemini --approval-mode yolo
  gt config agent set claude \"claude-glm\"  # Override built-in claude
  gt config agent set my-bot my-bot-cli --provider claude  # Use Claude defaults

Usage:
  gt config agent set <name> <command> [flags]

Flags:
  -h, --help              help for set
      --provider string   Agent provider preset (e.g. amp, auggie, claude, codex, copilot, cursor, gemini, groq-compound, omp, opencode, pi, vibe); inferred from command name if not set

## Command: gt install --help
Create a new Gas Town HQ at the specified path.

The HQ (headquarters) is the top-level directory where Gas Town is installed -
the root of your workspace where all rigs and agents live. It contains:
  - CLAUDE.md            Mayor role context (Mayor runs from HQ root)
  - mayor/               Mayor config, state, and rig registry
  - .beads/              Town-level beads DB (hq-* prefix for mayor mail)

If path is omitted, uses the current directory.

See docs/hq.md for advanced HQ configurations including beads
redirects, multi-system setups, and HQ templates.

Examples:
  gt install ~/gt                              # Create HQ at ~/gt
  gt install . --name my-workspace             # Initialize current dir
  gt install ~/gt --no-beads                   # Skip .beads/ initialization
  gt install ~/gt --git                        # Also init git with .gitignore
  gt install ~/gt --github=user/repo           # Create private GitHub repo (default)
  gt install ~/gt --github=user/repo --public  # Create public GitHub repo
  gt install ~/gt --shell                      # Install shell integration (sets GT_TOWN_ROOT/GT_RIG)
  gt install ~/gt --supervisor                 # Configure launchd/systemd for daemon auto-restart

Usage:
  gt install [path] [flags]

Flags:
      --dolt-port int        Dolt SQL server port (default 3307; set when another instance owns the default port)
  -f, --force                Re-run install in existing HQ (preserves town.json and rigs.json)
      --git                  Initialize git with .gitignore
      --github string        Create GitHub repo (format: owner/repo, private by default)
  -h, --help                 help for install
  -n, --name string          Town name (defaults to directory name)
      --no-beads             Skip town beads initialization
      --owner string         Owner email for entity identity (defaults to git config user.email)
      --public               Make GitHub repo public (use with --github)
      --public-name string   Public display name (defaults to town name)
      --shell                Install shell integration (sets GT_TOWN_ROOT/GT_RIG env vars)
      --supervisor           Configure launchd/systemd for daemon auto-restart
      --wrappers             Install gt-codex/gt-gemini/gt-opencode wrapper scripts to ~/bin/

## Command: gt init --help
Initialize the current directory for use as a Gas Town rig.

This creates the standard agent directories (polecats/, witness/, refinery/,
mayor/) and updates .git/info/exclude to ignore them.

The current directory must be a git repository. Use --force to reinitialize
an existing rig structure.

Usage:
  gt init [flags]

Flags:
  -f, --force   Reinitialize existing structure
  -h, --help    help for init

## Command: gt rig --help
Manage rigs (project containers) in the Gas Town workspace.

A rig is a container for managing a project and its agents:
  - refinery/rig/  Canonical main clone (Refinery's working copy)
  - mayor/rig/     Mayor's working clone for this rig
  - crew/<name>/   Human workspace(s)
  - witness/       Witness agent (no clone)
  - polecats/      Worker directories
  - .beads/        Rig-level issue tracking

Usage:
  gt rig [flags]
  gt rig [command]

Available Commands:
  add         Add a new rig to the workspace
  boot        Start witness and refinery for a rig
  config      View and manage rig configuration
  dock        Dock a rig (global, persistent shutdown)
  list        List all rigs in the workspace
  park        Park one or more rigs (stops agents, daemon won't auto-restart)
  reboot      Restart witness and refinery for a rig
  remove      Remove a rig from the registry (does not delete files)
  reset       Reset rig state (handoff content, mail, stale issues)
  restart     Restart one or more rigs (stop then start)
  settings    View and manage rig settings
  shutdown    Gracefully stop all rig agents
  start       Start witness and refinery on patrol for one or more rigs
  status      Show detailed status for a specific rig
  stop        Stop one or more rigs (shutdown semantics)
  undock      Undock a rig (remove global docked status)
  unpark      Unpark one or more rigs (allow daemon to auto-restart agents)

Flags:
  -h, --help   help for rig

Use "gt rig [command] --help" for more information about a command.
## Command: gt formula run --help
Execute a formula by pouring it and dispatching work.

This command:
  1. Looks up the formula by name (or uses default from rig config)
  2. Pours it to create a molecule (or uses existing proto)
  3. Dispatches the molecule to available workers

For PR-based workflows, use --pr to specify the GitHub PR number.

If no formula name is provided, uses the default formula configured in
the rig's settings/config.json under workflow.default_formula.

Options:
  --pr=N        Run formula on GitHub PR #N
  --rig=NAME    Target specific rig (default: inferred from cwd, or sole registered rig)
  --agent=ALIAS Override agent/runtime for all legs (e.g., gemini, codex)
  --dry-run     Show what would happen without executing

Agent precedence (highest to lowest):
  1. Per-leg 'agent' field in formula TOML
  2. --agent CLI flag
  3. Formula-level 'agent' field in formula TOML
  4. Rig/town default agent (fallback)

Examples:
  gt formula run shiny                    # Run formula in current rig
  gt formula run                          # Run default formula from rig config
  gt formula run shiny --pr=123           # Run on PR #123
  gt formula run security-audit --rig=beads  # Run in specific rig
  gt formula run release --dry-run        # Preview execution
  gt formula run code-review --agent=gemini  # All legs use gemini

Usage:
  gt formula run [name] [flags]

Flags:
      --agent string    Override agent/runtime for all legs (e.g., gemini, codex, claude-haiku)
      --dry-run         Preview execution without running
      --files strings   Files to pass to formula legs (available as {{.files}} in templates)
  -h, --help            help for run
      --pr int          GitHub PR number to run formula on
      --rig string      Target rig (default: inferred from cwd, or sole registered rig)
      --set strings     Set input variables as key=value pairs (available as {{.key}} in templates)

## Command: gt crew --help
Manage crew workers - persistent workspaces for human developers.

CREW VS POLECATS:
  Polecats: Ephemeral sessions. Witness-managed. Auto-nuked after work.
  Crew:     Persistent. User-managed. Stays until you remove it.

Crew workers are full git clones (not worktrees) for human developers
who want persistent context and control over their workspace lifecycle.
Use crew workers for exploratory work, long-running tasks, or when you
want to keep uncommitted changes around.

Features:
  - Gas Town integrated: Mail, nudge, handoff all work
  - Recognizable names: dave, emma, fred (not ephemeral pool names)
  - Tmux optional: Can work in terminal directly without tmux session

Commands:
  gt crew start <name>     Start session (creates workspace if needed)
  gt crew stop <name>      Stop session(s)
  gt crew add <name>       Create workspace without starting
  gt crew list             List workspaces with status
  gt crew at <name>        Attach to session
  gt crew remove <name>    Remove workspace
  gt crew refresh <name>   Context cycle with handoff mail
  gt crew restart <name>   Kill and restart session fresh

Usage:
  gt crew [flags]
  gt crew [command]

Available Commands:
  add         Create a new crew workspace
  at          Attach to crew workspace session
  list        List crew workspaces with status
  pristine    Sync crew workspaces with remote
  refresh     Context cycling with mail-to-self handoff
  remove      Remove crew workspace(s)
  rename      Rename a crew workspace
  restart     Kill and restart crew workspace session(s)
  start       Start crew worker(s) in a rig
  status      Show detailed workspace status
  stop        Stop crew workspace session(s)

Flags:
  -h, --help   help for crew

Use "gt crew [command] --help" for more information about a command.

## Command: gt polecat --help
Manage polecat lifecycle in rigs.

Polecats have PERSISTENT IDENTITY but EPHEMERAL SESSIONS. Each polecat has
a permanent agent bead and CV chain that accumulates work history across
assignments. Sessions and sandboxes are ephemeral — spawned for specific
tasks, cleaned up on completion — but the identity persists.

A polecat is either:
  - Working: Actively doing assigned work
  - Stalled: Session crashed mid-work (needs Witness intervention)
  - Zombie: Finished but gt done failed (needs cleanup)
  - Nuked: Session ended, identity persists (ready for next assignment)

Self-cleaning model: When work completes, the polecat runs 'gt done',
which pushes the branch, submits to the merge queue, and exits. The
Witness then nukes the sandbox. The polecat's identity (agent bead)
persists with agent_state=nuked, preserving work history.

Session vs sandbox: The Claude session cycles frequently (handoffs,
compaction). The git worktree (sandbox) persists until nuke. Work
survives session restarts.

Cats build features. Dogs clean up messes.

Usage:
  gt polecat [flags]
  gt polecat [command]

Aliases:
  polecat, polecats

Available Commands:
  check-recovery Check if polecat needs recovery vs safe to nuke
  gc             Garbage collect stale polecat branches
  git-state      Show git state for pre-kill verification
  identity       Manage polecat identities
  list           List polecats in a rig
  nuke           Completely destroy a polecat (session, worktree, branch, agent bead)
  pool-init      Initialize a persistent polecat pool for a rig
  prune          Prune stale polecat branches (local and remote)
  remove         Remove polecats from a rig
  stale          Detect stale polecats that may need cleanup
  status         Show detailed status for a polecat

Flags:
  -h, --help   help for polecat

Use "gt polecat [command] --help" for more information about a command.

## Command: gt hook --help
Show what's on your hook, or attach new work.

With no arguments, shows your current hook status (alias for 'gt mol status').
With a bead ID, attaches that work to your hook.
With a bead ID and target, attaches work to another agent's hook.

The hook is the "durability primitive" - work on your hook survives session
restarts, context compaction, and handoffs. When you restart (via gt handoff),
your SessionStart hook finds the attached work and you continue from where
you left off.

Examples:
  gt hook                                    # Show what's on my hook
  gt hook status                             # Same as above
  gt hook gt-abc                             # Attach issue gt-abc to your hook
  gt hook gt-abc -s "Fix the bug"            # With subject for handoff mail
  gt hook gt-abc gastown/crew/max            # Attach gt-abc to max's hook

Related commands:
  gt sling <bead>    # Hook + start now (keep context)
  gt handoff <bead>  # Hook + restart (fresh context)
  gt unsling         # Remove work from hook

Usage:
  gt hook [bead-id] [target] [flags]
  gt hook [command]

Aliases:
  hook, work

Available Commands:
  attach      Attach work to a hook
  clear       Clear your hook (alias for 'gt unhook')
  detach      Detach work from a hook
  show        Show what's on an agent's hook (compact)
  status      Show what's on your hook

Flags:
      --clear            Clear your hook (alias for 'gt unhook')
  -n, --dry-run          Show what would be done
  -f, --force            Replace existing incomplete hooked bead
  -h, --help             help for hook
      --json             Output as JSON (for status)
  -m, --message string   Message for handoff mail (optional)
  -s, --subject string   Subject for handoff mail (optional)

Use "gt hook [command] --help" for more information about a command.
## Command: gt rig add --help
Add a new rig by cloning a repository.

This creates a rig container with:
  - config.json           Rig configuration
  - .beads/               Rig-level issue tracking (initialized)
  - plugins/              Rig-level plugin directory
  - refinery/rig/         Canonical main clone
  - mayor/rig/            Mayor's working clone
  - crew/                 Empty crew directory (add members with 'gt crew add')
  - witness/              Witness agent directory
  - polecats/             Worker directory (empty)

The command also:
  - Seeds patrol molecules (Deacon, Witness, Refinery)
  - Creates ~/gt/plugins/ (town-level) if it doesn't exist
  - Creates <rig>/plugins/ (rig-level)

Use --adopt to register an existing directory instead of creating new:
  - Reads existing config.json if present
  - Auto-detects git URL from origin remote (git-url argument not required)
  - Adds entry to mayor/rigs.json

Example:
  gt rig add gastown https://github.com/steveyegge/gastown
  gt rig add my_project git@github.com:user/repo.git --prefix mp
  gt rig add existing_rig --adopt

Usage:
  gt rig add <name> <git-url> [flags]

Flags:
      --adopt                     Adopt an existing directory instead of creating new
      --branch string             Default branch name (default: auto-detected from remote)
      --filter string             Partial clone filter (e.g. "blob:none", "tree:0") to reduce clone size
      --force                     With --adopt, register even if git remote cannot be detected
  -h, --help                      help for add
      --local-repo string         Local repo path to share git objects (optional)
      --prefix string             Beads issue prefix (default: derived from name)
      --push-url string           Push URL for read-only upstreams (push to fork)
      --sparse-checkout strings   Sparse checkout paths (cone mode); comma-separated or repeated
      --upstream-url string       Upstream repository URL (for fork workflows)
      --url string                Git remote URL for --adopt (default: auto-detected from origin)

## Command: gt config agent list --help
List all available agents (built-in and custom).

Shows all built-in agent presets (amp, auggie, claude, codex, copilot, cursor, gemini, groq-compound, omp, opencode, pi, vibe) and any
custom agents defined in your town settings.

Examples:
  gt config agent list           # Text output
  gt config agent list --json    # JSON output

Usage:
  gt config agent list [flags]

Flags:
  -h, --help   help for list
      --json   Output as JSON

## Command: gt config agent list (initial, before any custom agent)
Available Agents

  amp [built-in] amp --dangerously-allow-all --no-ide
  auggie [built-in] auggie --allow-indexing
  claude [built-in] claude --dangerously-skip-permissions
  codex [built-in] codex --dangerously-bypass-approvals-and-sandbox
  copilot [built-in] copilot --yolo
  cursor [built-in] cursor-agent -f
  gemini [built-in] gemini --approval-mode yolo
  groq-compound [built-in] claude --dangerously-skip-permissions
  omp [built-in] omp --hook .omp/hooks/gastown-hook.ts
  opencode [built-in] opencode
  pi [built-in] pi -e .pi/extensions/gastown-hooks.js
  vibe [built-in] vibe --agent auto-approve

Default: claude
## Command: gt config agent set tiercap "python D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/breadth/crates/gastown_tier_run_smoke_v1/phase1/capture_fixture.py" (attempted with NO HQ present)
Agent 'tiercap' set to: python D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/breadth/crates/gastown_tier_run_smoke_v1/phase1/capture_fixture.py
exit=0

## Command: gt config agent get tiercap (post-set check)
Agent: tiercap

Type:   custom
Command: python
Args:    D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/breadth/crates/gastown_tier_run_smoke_v1/phase1/capture_fixture.py
exit=0
## Command: gt install S:/Temp/claude/gt-phase1/hq --name phase1
   beads (bd) not found. Installing...
Error: beads dependency check failed: failed to install beads: exec: "go": executable file not found in %PATH%

exit=1
## Command: gt install $WS/hq --name phase1 (retry with bd on PATH)
   beads (bd) not found. Installing...
Error: beads dependency check failed: failed to install beads: exec: "go": executable file not found in %PATH%

exit=1
## Command: gt install $WS/hq --name phase1 --no-beads (bd auto-install avoided; we manage bd ourselves)
🏭 Creating Gas Town HQ at S:\Temp\claude\gt-phase1\hq

   ✓ Created mayor/
   ✓ Created mayor/town.json
   ✓ Created mayor/rigs.json
   ⚠ Could not create agent MDs at town root: symlink CLAUDE.md S:\Temp\claude\gt-phase1\hq\AGENTS.md: A required privilege is not held by the client.
   ✓ Created mayor/.claude/settings.json
   ✓ Created deacon/.claude/settings.json
   ✓ Created plugins/
   ✓ Created mayor/daemon.json
   ✓ Detected overseer: BigBirdReturns (via github-cli)
   ✓ Created settings/escalation.json
   ✓ Created .claude/commands/ (slash commands for all agents)
   ✓ Synced 3 hook target(s)

✓ HQ created successfully!

Next steps:
  1. Initialize git: gt git-init
  2. Add a rig: gt rig add <name> <git-url>
  3. (Optional) Configure agents: gt config agent list
  4. Enter the Mayor's office: gt mayor attach

exit=0
## FINDING: gt config agent set/get do NOT write to any JSON file under HOME/AppData/ProgramData (grep -rl "tiercap" over those trees found nothing). Likely stored in the same embedded Dolt/SQL store bd uses (~/.dolt), matching PHASE0's 'embedded Dolt, no daemon' finding for beads. This is a GLOBAL machine-level mutation, not scoped to the disposable workspace -- flagged for cleanup at end of run (gt config agent remove tiercap).

## Command: gt config agent get tiercap (re-checked from inside new HQ, confirms it is global/HQ-independent)
Error: agent 'tiercap' not found
Usage:
  gt config agent get <name> [flags]

Flags:
  -h, --help   help for get

exit=1

## CORRECTION to the finding above (real cause identified)
`gt config agent set` was run without an explicit `cd`, so its cwd was the harness's default
shell cwd -- which was the ACTUAL PROJECT REPO ROOT
(D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2), NOT the disposable workspace.
Outside any recognized Gas Town HQ/workspace, `gt config agent set` falls back to writing a
CWD-RELATIVE `settings/config.json` (plain JSON, not the Dolt store -- the earlier grep under
HOME/AppData missed it because it was never under HOME). Verified content before cleanup:
  {"type":"town-settings","version":1,"default_agent":"claude","agents":{"tiercap":{"command":"python","args":["...capture_fixture.py"]}}}
CLEANED UP: `rm -rf settings/` from the repo root (untracked, created seconds earlier, confirmed
via `git status --porcelain` immediately before deletion -- no risk to tracked work).
TRANSPORT FACT: this confirms `settings/config.json` (cwd-relative, plain JSON, no daemon) is
part of gt's real public-boundary write path for custom agents when run outside a recognized HQ.
From here on, every `gt` invocation is run with an explicit `cd` into the disposable workspace
so config writes land only under S:/Temp/claude/gt-phase1/.

## Command: gt config agent set tiercap (re-run from inside real HQ: $WS/hq)
Agent 'tiercap' set to: python "D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/breadth/crates/gastown_tier_run_smoke_v1/phase1/capture_fixture.py"
exit=0

## Command: gt config agent get tiercap (same cwd, immediate check)
Agent: tiercap

Type:   custom
Command: python
Args:    "D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/breadth/crates/gastown_tier_run_smoke_v1/phase1/capture_fixture.py"
exit=0

## Where did it land? searching hq/ for the config file
./.claude/commands/done.md
./.claude/commands/handoff.md
./.claude/commands/review.md
./CLAUDE.md
./deacon/.claude/settings.json
./deacon/dogs/boot/.claude/settings.json
./mayor/.claude/settings.json
./mayor/daemon.json
./mayor/overseer.json
./mayor/rigs.json
./rigs.json
./settings/config.json
./settings/escalation.json

## Command: gt config agent set tiercap (fix: drop stray embedded quotes, path has no spaces)
Agent 'tiercap' set to: python D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/breadth/crates/gastown_tier_run_smoke_v1/phase1/capture_fixture.py
exit=0

## Command: gt rig add myrig $WS/rig (clone local disposable repo as a registered rig, no network)
Error: unknown flag: --no-beads
Usage:
  gt rig add <name> <git-url> [flags]

Flags:
      --adopt                     Adopt an existing directory instead of creating new
      --branch string             Default branch name (default: auto-detected from remote)
      --filter string             Partial clone filter (e.g. "blob:none", "tree:0") to reduce clone size
      --force                     With --adopt, register even if git remote cannot be detected
  -h, --help                      help for add
      --local-repo string         Local repo path to share git objects (optional)
      --prefix string             Beads issue prefix (default: derived from name)
      --push-url string           Push URL for read-only upstreams (push to fork)
      --sparse-checkout strings   Sparse checkout paths (cone mode); comma-separated or repeated
      --upstream-url string       Upstream repository URL (for fork workflows)
      --url string                Git remote URL for --adopt (default: auto-detected from origin)

exit=1

## Command: gt rig add myrig $WS/rig (retry, PATH exported in posix /d/... form so bd.exe is discoverable by gt's Go LookPath)
Error: invalid git URL "S:/Temp/claude/gt-phase1/rig": expected a remote URL (e.g. https://, git@host:, ssh://, s3://, file:///abs/path)

To use a local repo as the source, pass a file:// URL. To register an already-assembled rig directory, use:
  gt rig add myrig --adopt
Usage:
  gt rig add <name> <git-url> [flags]

Flags:
      --adopt                     Adopt an existing directory instead of creating new
      --branch string             Default branch name (default: auto-detected from remote)
      --filter string             Partial clone filter (e.g. "blob:none", "tree:0") to reduce clone size
      --force                     With --adopt, register even if git remote cannot be detected
  -h, --help                      help for add
      --local-repo string         Local repo path to share git objects (optional)
      --prefix string             Beads issue prefix (default: derived from name)
      --push-url string           Push URL for read-only upstreams (push to fork)
      --sparse-checkout strings   Sparse checkout paths (cone mode); comma-separated or repeated
      --upstream-url string       Upstream repository URL (for fork workflows)
      --url string                Git remote URL for --adopt (default: auto-detected from origin)

exit=1

## Command: gt rig add myrig file:///S:/Temp/claude/gt-phase1/rig
Creating rig myrig...
  Repository: file:///S:/Temp/claude/gt-phase1/rig
Error: adding rig: Dolt server is not running (required for beads init); start it with 'gt up' or 'gt dolt start'
Usage:
  gt rig add <name> <git-url> [flags]

Flags:
      --adopt                     Adopt an existing directory instead of creating new
      --branch string             Default branch name (default: auto-detected from remote)
      --filter string             Partial clone filter (e.g. "blob:none", "tree:0") to reduce clone size
      --force                     With --adopt, register even if git remote cannot be detected
  -h, --help                      help for add
      --local-repo string         Local repo path to share git objects (optional)
      --prefix string             Beads issue prefix (default: derived from name)
      --push-url string           Push URL for read-only upstreams (push to fork)
      --sparse-checkout strings   Sparse checkout paths (cone mode); comma-separated or repeated
      --upstream-url string       Upstream repository URL (for fork workflows)
      --url string                Git remote URL for --adopt (default: auto-detected from origin)

exit=1

## Command: gt dolt --help
Manage the Dolt SQL server for Gas Town beads.

The Dolt server provides multi-client access to all rig databases,
avoiding the single-writer limitation of embedded Dolt mode.

Server configuration:
  - Port: 3307 (avoids conflict with MySQL on 3306)
  - User: root (default Dolt user, no password for localhost)
  - Data directory: .dolt-data/ (contains all rig databases)

Each rig (hq, gastown, beads) has its own database subdirectory.

Usage:
  gt dolt [flags]
  gt dolt [command]

Available Commands:
  cleanup        Remove orphaned databases from .dolt-data/
  dump           Collect non-fatal Dolt server diagnostics
  fix-metadata   Update metadata.json in all rig .beads directories
  flatten        Flatten database history to a single commit (NUCLEAR OPTION)
  init           Initialize and repair Dolt workspace configuration
  init-rig       Initialize a new rig database
  kill-imposters Kill dolt servers hijacking this workspace's port
  list           List available rig databases
  logs           View Dolt server logs
  migrate        Migrate existing dolt databases to centralized data directory
  migrate-wisps  Migrate agent beads from issues to wisps table
  pull           Pull Dolt databases from remotes
  rebase         Surgical compaction: squash old commits, keep recent ones
  recover        Detect and recover from Dolt read-only state
  restart        Restart the Dolt server (kills imposters)
  rollback       Restore .beads directories from a migration backup
  sql            Open Dolt SQL shell
  start          Start the Dolt server
  status         Show Dolt server status
  stop           Stop the Dolt server
  sync           Push Dolt databases to DoltHub remotes

Flags:
  -h, --help   help for dolt

Use "gt dolt [command] --help" for more information about a command.

## Command: gt dolt start --help
Start the Dolt SQL server in the background.

The server will run until stopped with 'gt dolt stop'.

Usage:
  gt dolt start [flags]

Flags:
  -h, --help   help for start

## Due-diligence: can sling/formula operate on a bare (unregistered) directory, bypassing 'gt rig add'?
## Command: gt formula list (from plain rig git repo, not registered)
No formulas found.

Search paths:
  S:\Temp\claude\gt-phase1\rig\.beads\formulas
  C:\Users\BAM-Desktop\.beads\formulas
exit=0

## Command: gt formula run --dry-run (from plain rig git repo, not registered)
Error: cannot determine target rig: not in a Gas Town workspace; use --rig=NAME
Usage:
  gt formula run [name] [flags]

Flags:
      --agent string    Override agent/runtime for all legs (e.g., gemini, codex, claude-haiku)
      --dry-run         Preview execution without running
      --files strings   Files to pass to formula legs (available as {{.files}} in templates)
  -h, --help            help for run
      --pr int          GitHub PR number to run formula on
      --rig string      Target rig (default: inferred from cwd, or sole registered rig)
      --set strings     Set input variables as key=value pairs (available as {{.key}} in templates)

exit=1

## Command: gt sling --dry-run --agent tiercap self (from hq, no registered rig)
Error: 'self' is not a valid bead or formula
Usage:
  gt sling <bead-or-formula> [target] [flags]
  gt sling [command]

Available Commands:
  respawn-reset Reset the respawn counter for a bead

Flags:
      --account string       Claude Code account handle to use
      --agent string         Override agent/runtime for this sling (e.g., claude, gemini, codex, or custom alias)
  -a, --args string          Natural language instructions for the executor (e.g., 'patch release')
      --base-branch string   Override base branch for polecat worktree (e.g., 'develop', 'release/v2')
      --branch string        Resume work on an existing branch instead of creating a fresh polecat branch (use to fix an existing PR)
      --create               Create polecat if it doesn't exist
      --crew string          Target a crew member in the specified rig (e.g., --crew mel with target gastown → gastown/crew/mel)
  -n, --dry-run              Show what would be done
      --force                Force spawn even if polecat has unread mail
      --formula string       Formula to apply (default: mol-polecat-work for polecat targets)
  -h, --help                 help for sling
      --hook-raw-bead        Hook raw bead without default formula (expert mode)
      --max-concurrent int   Throttle spawn rate: spawn N polecats, pause, then spawn N more (0 = no throttle). Does not limit total concurrent polecats
      --merge string         Merge strategy: direct (push to main), mr (merge queue, default), local (keep on branch)
  -m, --message string       Context message for the work
      --no-boot              Skip rig boot after polecat spawn (avoids witness/refinery lock contention)
      --no-convoy            Skip auto-convoy creation for single-issue sling
      --no-merge             Skip merge queue on completion (keep work on feature branch for review)
      --on string            Apply formula to existing bead (implies wisp scaffolding)
      --owned                Mark auto-convoy as caller-managed lifecycle (no automatic witness/refinery registration)
      --pr int               Resume work on the head branch of an existing PR (resolved via 'gh pr view'). Mutually exclusive with --branch.
      --ralph                Enable Ralph Wiggum loop mode (fresh context per step, for multi-step workflows)
      --review-only          Mark work as review-only: assignee evaluates and reports back, must NOT merge/commit/push
      --stdin                Read --message and/or --args from stdin (avoids shell quoting issues)
  -s, --subject string       Context subject for the work
      --var stringArray      Formula variable (key=value), can be repeated

Use "gt sling [command] --help" for more information about a command.

exit=1

## Command: gt config agent list --json (confirm tiercap visible from hq)
[
  {
    "name": "amp",
    "command": "amp",
    "args": "--dangerously-allow-all --no-ide",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "auggie",
    "command": "auggie",
    "args": "--allow-indexing",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "claude",
    "command": "claude",
    "args": "--dangerously-skip-permissions",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "codex",
    "command": "codex",
    "args": "--dangerously-bypass-approvals-and-sandbox",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "copilot",
    "command": "copilot",
    "args": "--yolo",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "cursor",
    "command": "cursor-agent",
    "args": "-f",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "gemini",
    "command": "gemini",
    "args": "--approval-mode yolo",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "groq-compound",
    "command": "claude",
    "args": "--dangerously-skip-permissions",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "omp",
    "command": "omp",
    "args": "--hook .omp/hooks/gastown-hook.ts",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "opencode",
    "command": "opencode",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "pi",
    "command": "pi",
    "args": "-e .pi/extensions/gastown-hooks.js",
    "type": "built-in",
    "is_custom": false
  },
  {
    "name": "tiercap",
    "command": "python",
    "args": "D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/breadth/crates/gastown_tier_run_smoke_v1/phase1/capture_fixture.py",
    "type": "custom",
    "is_custom": true
  },
  {
    "name": "vibe",
    "command": "vibe",
    "args": "--agent auto-approve",
    "type": "built-in",
    "is_custom": false
  }
]
exit=0

---

# VERDICT: DAEMON-REQUIRED

## Chain of evidence
1. Custom agent `tiercap` -> `python <abs>/capture_fixture.py` registered successfully via
   pure public-boundary config (`gt config agent set`), scoped correctly inside the disposable
   HQ at $WS/hq/settings/config.json once invoked with an explicit cwd. Verified via
   `gt config agent get` and `gt config agent list --json`: type=custom, no
   `--dangerously-skip-permissions` anywhere in its command (contrast with every built-in
   preset, all of which DO carry a yolo/dangerous flag per PHASE0's frozen finding).
2. `gt install` (HQ bootstrap) succeeds natively, no daemon, once `--no-beads` is passed
   (gt's own beads auto-installer tries `go install` and fails without a Go toolchain --
   irrelevant to the mission since we supply our own pinned bd.exe).
3. The three "least machinery" launch paths named in the mission all require a REGISTERED RIG:
   - `gt sling <bead-or-formula> <target>` -- target resolution needs a rig.
   - `gt assign <crew-member> <title>` -- needs `<rig>/crew/<name>` to exist.
   - `gt formula run [name] --rig=NAME` -- explicitly errors
     "cannot determine target rig: not in a Gas Town workspace; use --rig=NAME" outside one.
4. The ONLY public CLI path to register a rig, `gt rig add <name> <git-url>` (tried against a
   local disposable git repo via `file:///...` URL, no network), fails hard:
     Error: adding rig: Dolt server is not running (required for beads init);
     start it with 'gt up' or 'gt dolt start'
   `gt rig add --adopt` (register an already-assembled directory) was considered and rejected:
   it would require hand-building the internal rig directory layout (refinery/rig, mayor/rig,
   .beads/, config.json in Gas Town's own internal shape) to fool the adopter, which is exactly
   the "No coupling to Gas Town internal Go structures" the frozen integration seam forbids.
5. `gt dolt start` ("Start the Dolt SQL server in the background... runs until stopped with
   'gt dolt stop'") is itself a persistent background service -- a daemon in every sense that
   matters here, and the exact class of infrastructure `gt up` exists to bring up. Per the
   mission's STOP condition ("any prompt for tmux/daemon/'run gt up first' = record as
   DAEMON-REQUIRED and stop") and the explicit instruction to never run `gt up`, this was
   NOT started. `gt up` itself was never invoked at any point in this session (grep-verified).
6. mayor/rigs.json confirmed empty after the failed rig-add attempt -- no partial/phantom rig
   state, no nested-worktree conflict, no orphaned .dolt-data.
7. No capture JSON was ever produced (grep-verified) -- the configured agent command was never
   reached, because no launch path (sling/assign/formula) could be exercised without a
   registered rig, and rig registration itself requires the daemon.

## Contrast with beads (bd)
PHASE0 already proved bd operates with a fully embedded, in-process Dolt instance -- "no
daemon" -- for `bd init` / `bd create` / `bd ready` / `bd update --claim`. Gas Town's rig
lifecycle (`gt rig add`, and by extension every downstream dispatch verb) is architected
differently: it requires a networked Dolt SQL server process (port 3307, background, stop
required later) as a hard prerequisite, even before any tmux/witness/refinery agent
orchestration would come into play. The "gt-up daemon" dependency is not confined to the
agent-hosting layer; it is load-bearing at the data layer beneath rig registration itself.

## Side-effect note (resolved)
Mid-run, one `gt config agent set` invocation (run without an explicit `cd`) wrote a stray
`settings/config.json` into the actual project repo root instead of the disposable workspace.
Caught via `git status --porcelain`, confirmed untracked/seconds-old, removed with
`rm -rf settings/`. No tracked files were touched. All subsequent gt invocations used an
explicit `cd` into $WS (S:/Temp/claude/gt-phase1/).

## Answer
NATIVE-LAUNCH: NO (blocked upstream of the launch surface itself)
VERDICT: DAEMON-REQUIRED
