import type { PropsWithChildren } from "react";

export function FilterBar({ children }: PropsWithChildren) {
  return <div className="filter-bar panel">{children}</div>;
}
