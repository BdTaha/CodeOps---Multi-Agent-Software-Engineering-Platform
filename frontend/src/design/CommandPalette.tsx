import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Search } from "lucide-react";
import type { Workbench } from "../useWorkbench";
import type { View } from "../types";
import { getWorkspace } from "../teamApi";
import { openRun, openTask } from "../engineering/navigation";

interface Command {
  id: string;
  label: string;
  detail: string;
  run: () => void;
}
export default function CommandPalette({
  lab,
  navigate,
}: {
  lab: Workbench;
  navigate: (view: View) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const [tasks, setTasks] = useState<
    Awaited<ReturnType<typeof getWorkspace>>["tasks"]
  >([]);
  const [loadError, setLoadError] = useState(false);
  function show() {
    setQuery("");
    setIndex(0);
    setLoadError(false);
    dialog.current?.showModal();
    input.current?.focus();
    void getWorkspace()
      .then((result) => setTasks(result.tasks))
      .catch(() => setLoadError(true));
  }
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        dialog.current?.open ? dialog.current.close() : show();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const commands = useMemo<Command[]>(
    () => [
      ...(
        [
          "projects",
          "planning",
          "board",
          "teams",
          "workspace",
          "models",
        ] as View[]
      ).map((view) => ({
        id: view,
        label:
          view === "workspace"
            ? "Open Engineering"
            : `Open ${view[0].toUpperCase() + view.slice(1)}`,
        detail: "Navigate",
        run: () => navigate(view),
      })),
      {
        id: "goal",
        label: "New product goal",
        detail: "Planning",
        run: () => {
          navigate("planning");
          requestAnimationFrame(() =>
            document.getElementById("project-goal")?.focus(),
          );
        },
      },
      {
        id: "review",
        label: "Open human review queue",
        detail: "Engineering",
        run: () => {
          navigate("workspace");
          window.location.hash = "#/engineering/reviews";
        },
      },
      ...lab.projects.map((project) => ({
        id: project.id,
        label: `Open ${project.name}`,
        detail: "Project",
        run: () => lab.openProject(project),
      })),
      ...tasks.map((task) => ({
        id: task.id,
        label: `${task.key} · ${task.title}`,
        detail: task.status.replaceAll("_", " "),
        run: () => {
          navigate("workspace");
          openTask(task.id);
        },
      })),
      ...lab.sessionRuns.map((run) => ({
        id: run.run_id,
        label: `Run ${run.run_id.slice(0, 12)} · ${run.task.request.user_request}`,
        detail: run.task.status,
        run: () => {
          navigate("workspace");
          openRun(run.task.task_id);
        },
      })),
    ],
    [lab.projects, lab.sessionRuns, tasks, navigate],
  );
  const matches = commands
    .filter((command) =>
      `${command.label} ${command.detail}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .slice(0, 35);
  const active = Math.min(index, Math.max(0, matches.length - 1));
  function choose(command: Command) {
    dialog.current?.close();
    command.run();
  }
  useEffect(() => {
    document
      .getElementById(`command-${active}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);
  return (
    <>
      <button
        ref={trigger}
        className="command-trigger"
        onClick={show}
        aria-label="Search CodeOps commands and tasks"
      >
        <Search size={14} />
        <span>Search or jump to…</span>
        <kbd>⌘ / Ctrl K</kbd>
      </button>
      <dialog
        ref={dialog}
        className="command-dialog"
        aria-label="Search CodeOps"
        onClose={() => trigger.current?.focus()}
        onClick={(event) => {
          if (event.target === dialog.current) dialog.current?.close();
        }}
      >
        <div className="command-input">
          <Search size={18} />
          <input
            ref={input}
            value={query}
            placeholder="Search commands, projects, tasks or runs…"
            role="combobox"
            aria-expanded="true"
            aria-controls="command-results"
            aria-activedescendant={
              matches.length ? `command-${active}` : undefined
            }
            autoComplete="off"
            onChange={(event) => {
              setQuery(event.target.value);
              setIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                setIndex(
                  (active +
                    (event.key === "ArrowDown" ? 1 : -1) +
                    Math.max(matches.length, 1)) %
                    Math.max(matches.length, 1),
                );
              }
              if (event.key === "Enter" && matches[active]) {
                event.preventDefault();
                choose(matches[active]);
              }
            }}
          />
          <button
            className="text-button"
            onClick={() => dialog.current?.close()}
          >
            Esc
          </button>
        </div>
        <div
          className="command-results"
          id="command-results"
          role="listbox"
          aria-label="Results"
        >
          {matches.map((command, i) => (
            <button
              key={command.id}
              id={`command-${i}`}
              role="option"
              aria-selected={active === i}
              onPointerMove={() => setIndex(i)}
              onClick={() => choose(command)}
            >
              <span>
                <strong>{command.label}</strong>
                <small>{command.detail}</small>
              </span>
              <ArrowUpRight size={14} />
            </button>
          ))}
          {!matches.length && <p>No matching commands or work.</p>}
        </div>
        <footer>
          <span>
            {loadError
              ? "Task search unavailable · navigation still works"
              : "Navigate without changing work"}
          </span>
          <span>↑ ↓ select · ↵ open</span>
        </footer>
      </dialog>
    </>
  );
}
