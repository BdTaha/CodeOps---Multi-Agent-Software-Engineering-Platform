import { Bell, Check, CircleAlert } from "lucide-react";
import type { Workbench } from "../useWorkbench";

export default function EventStack({ lab }: { lab: Workbench }) {
  const events = lab.sessionRuns
    .flatMap((run) => {
      const label =
        run.task.status === "failed"
          ? "Execution failed"
          : run.task.status === "succeeded"
            ? "Execution completed · inspect evidence"
            : null;
      return label
        ? [
            {
              id: run.run_id,
              label,
              detail: run.task.request.user_request,
              failed: run.task.status === "failed",
              run,
            },
          ]
        : [];
    })
    .slice(0, 8);
  return (
    <details className="event-stack">
      <summary
        aria-label={`Execution events, ${events.length} retained results`}
      >
        <Bell size={15} />
        {events.length > 0 && <span>{events.length}</span>}
      </summary>
      <div className="event-popover">
        <header>
          Execution events <small>Retained results</small>
        </header>
        {!events.length && <p>No completed execution results yet.</p>}
        {events.map((event) => (
          <button
            key={event.id}
            onClick={(e) => {
              e.currentTarget.closest("details")?.removeAttribute("open");
              void lab.openExecution(event.run.task.task_id);
            }}
          >
            {event.failed ? <CircleAlert size={15} /> : <Check size={15} />}
            <span>
              <strong>{event.label}</strong>
              <small>{event.detail}</small>
            </span>
          </button>
        ))}
      </div>
    </details>
  );
}
