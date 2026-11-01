# Interface design

CodeOps uses graphite surfaces, neutral off-white text and a restrained steel-blue
accent. Success, attention, failure and informational states have separate tokens.
`frontend/src/design/tokens.css` owns the palette, type stacks, spacing scale,
radii, control sizes, focus ring and motion duration. Domain layout styles consume
these tokens; `design/surfaces.css` owns shared interaction treatments.

Ordinary interface text uses the system sans-serif stack. Task keys, paths, model
IDs, commands, logs and source use the monospace stack. Buttons remain compact;
Engineering retains its task browser, workflow rail, nine tabs and file navigator.
Changes to status or evidence presentation do not create a second lifecycle model.

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

- [Spotlight Card](https://21st.dev/@jahed/components/spotlight-card): restrained
  pointer-following illumination, independently implemented in CSS and React.
- [Kokonut v0 AI Chat](https://21st.dev/@kokonutd/components/v0-ai-chat): a contained
  prompt composer for deliberate AI requests, not a chat-based application layout.
- [Pasta UI](https://21st.dev/@syeddhasnainn): compact agent activity, approval,
  file-diff and evidence patterns. Its public approval/status references identify
  MIT licensing; no third-party component source was imported.

CodeOps keeps its own domain components, accessible native controls and existing
Lucide and Prism dependencies. No animation framework or UI kit was added.
