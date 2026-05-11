import type { PropsWithChildren } from "react";

export function LoadingState({ children }: PropsWithChildren) {
  return <div className="panel state-panel">{children ?? "Loading..."}</div>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="panel state-panel">
      <h2>Error</h2>
      <pre>{message}</pre>
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}
