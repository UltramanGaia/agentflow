export function StatusBadge({ status }: { status: string }) {
  return <span className={`pill status-${status}`}>{status}</span>;
}
