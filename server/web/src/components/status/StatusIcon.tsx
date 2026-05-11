const ICON_BY_STATUS: Record<string, string> = {
  completed: "OK",
  running: "GO",
  failed: "!!",
  cancelled: "XX",
  cancelling: "XX",
  pending: "..",
  ready: "..",
  queued: "..",
};

export function StatusIcon({ status }: { status: string }) {
  return (
    <span aria-hidden="true" className={`status-icon status-${status}`}>
      {ICON_BY_STATUS[status] ?? ".."}
    </span>
  );
}
