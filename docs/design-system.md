# Interface design

CodeOps uses the user's dark desktop-editor reference: neutral charcoal surfaces,
compact chrome, flat lists, thin dividers and a large artifact area. Color is
reserved for evidence, statuses and source changes. There is no large brand tile,
promotional hero, decorative glow or card-based landing screen.

`frontend/src/design/tokens.css` owns colors, type stacks, spacing and controls.
`design/surfaces.css` owns shared interaction treatments;
`design/workspace.css` owns the current desktop shell, pane geometry and responsive
presentation. Existing domain styles retain their structural and semantic roles.

## Workspace direction

The palette is background `#1c1c1c`, navigation `#222222`, raised surface `#252525`,
divider `#343434`, text `#e4e4e4` and secondary text `#b4b4b4`. Primary buttons use
light neutral fill. Muted green, amber and red communicate actual recorded states;
they are not used as branding. Typography uses Segoe UI Variable with system
fallbacks, including headings. Source, commands and paths retain monospace text.
No external fonts, animation framework or UI kit are required.

The sidebar uses the user's supplied cube-and-spark logo. Its original transparent
PNG provides the CSS mask, so the mark inherits the surface's foreground color
without altering the artwork. Browser favicons use the supplied black version for
light browser chrome and white version for dark browser chrome. Both files are
bundled locally and work under the normal `/ui/` and showcase `/` bases.

The desktop shell has a modest inset and narrow frame. The sidebar uses a small
inline wordmark, compact navigation and registered-project links. User choices to
collapse the sidebar remain saved. Projects uses a repository list beside current
project context. Planning places the goal and saved-plan selection in a separate
scrolling pane beside the editable draft. Board uses neutral lanes and compact
tasks. Teams uses flat identity/capacity rows. Models retains provider/routing
sections with quiet borders.

Engineering places the task context, file list and retained attempts beside the
artifact viewer. A bottom execution strip uses the existing stage model and
navigation handlers, including the selected historical run's actual evidence.
This strip is a process navigator, not a fabricated time or progress chart.
The nine tabs, historical mode, coding-plan approval, acceptance acknowledgment,
model execution and delivery rules are retained. On narrow viewports the context
pane stacks above the artifact; code and the stage strip scroll within their own
regions, and both sidebar-collapse controls remain available.

The earlier light/navy direction was rejected by the user and replaced. The supplied
dark editor screenshot controls this revision's typography, surface treatment,
density and pane composition. Its film-specific controls and content were not
copied into CodeOps. Current captures are in `docs/screenshots`.

Pointer illumination is disabled by the current visual stylesheet. The reusable
`Spotlight` wrapper remains available, without React state updates on pointer move.
Reduced-motion preferences still disable animation and transitions. Visible focus
rings, native inputs and existing dialog focus containment are retained.

The command palette uses the native modal dialog's focus containment, Escape
handling and focus restoration, with a keyboard-controlled result list. Ctrl+K or
Cmd+K opens it. Results navigate to commands, registered projects, tasks and retained
runs; they do not execute or deliver work. The event stack lists actual retained
terminal results supplied by the current data boundary.

## References and provenance

The following are design references, not copied source or dependencies:

- [Anthropic frontend-design skill](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md):
  applied for the follow-up visual direction, typography, layout hierarchy and
  self-critique. The skill was read as guidance; no runtime package was installed.

- [Spotlight Card](https://21st.dev/@jahed/components/spotlight-card): restrained
  pointer-following illumination, independently implemented in CSS and React.
- [Kokonut v0 AI Chat](https://21st.dev/@kokonutd/components/v0-ai-chat): a contained
  prompt composer for deliberate AI requests, not a chat-based application layout.
- [Pasta UI](https://21st.dev/@syeddhasnainn): compact agent activity, approval,
  file-diff and evidence patterns. Its public approval/status references identify
  MIT licensing; no third-party component source was imported.

CodeOps keeps its own domain components, accessible native controls and existing
Lucide and Prism dependencies. No animation framework or UI kit was added.
