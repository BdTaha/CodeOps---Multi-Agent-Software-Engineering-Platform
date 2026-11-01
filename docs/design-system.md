# Interface design

CodeOps uses a pale blue work canvas, white document surfaces, deep navy navigation
and cobalt actions. Success, attention, failure and informational states have separate tokens.
`frontend/src/design/tokens.css` owns the palette, type stacks, spacing scale,
radii, control sizes, focus ring and motion duration. Domain layout styles consume
these tokens; `design/surfaces.css` owns shared interaction treatments and
`design/workspace.css` owns the current workspace presentation and responsive layout.

Ordinary interface text uses Segoe UI Variable with system fallbacks. Display
headings use Bahnschrift with Aptos Display and system fallbacks; no font service
or network dependency is needed. Task keys, paths, model IDs, commands, logs and
source use the monospace stack. Buttons remain compact;
Engineering retains its task browser, workflow rail, nine tabs and file navigator.
Changes to status or evidence presentation do not create a second lifecycle model.

## Workspace direction

The November 1 follow-up replaces the earlier graphite treatment with a visibly
different studio workspace. The palette is canvas `#edf1f7`, paper `#ffffff`,
navigation `#142644`, ink `#172848`, cobalt `#2958d9`, and green `#17714f`.
Content stays left aligned; display type identifies the page while compact sans
text carries controls and technical records.

Projects opens with repository context and a three-stage explanation of the real
plan/build/review flow, followed by repositories and working navigation shortcuts.
Planning uses a contained composer and separate editable draft sections. Board
lanes use restrained status tints, with white task surfaces. Teams uses identity
and capacity sections. Engineering uses a task header, tab strip, file navigator
and a paper evidence area; code keeps line numbers and distinct addition/deletion
backgrounds. Models uses clearly bounded provider and routing sections.

The emphasis is navigation versus working content, rather than decorative
animation. Shared state, transport, model execution, approval and delivery logic
remain unchanged. Sidebar preference is retained; a fresh desktop session starts
expanded and a fresh narrow-screen session starts collapsed. Both controls remain
available. Reduced-motion and keyboard-focus treatments are retained.

`Spotlight` updates CSS custom properties directly on pointer movement. Only
project and provider surfaces use it. No React state updates occur on pointer move.
Reduced-motion preferences remove the effect and disable motion throughout the UI.

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
