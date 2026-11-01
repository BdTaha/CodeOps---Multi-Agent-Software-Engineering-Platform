import type { HTMLAttributes } from "react";

export default function Spotlight({
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...props}
      className={`spotlight ${className}`}
      onPointerMove={(event) => {
        if (
          event.pointerType === "touch" ||
          window.matchMedia("(prefers-reduced-motion: reduce)").matches
        )
          return;
        const target = event.currentTarget;
        const rect = target.getBoundingClientRect();
        target.style.setProperty(
          "--pointer-x",
          `${event.clientX - rect.left}px`,
        );
        target.style.setProperty(
          "--pointer-y",
          `${event.clientY - rect.top}px`,
        );
      }}
    />
  );
}
