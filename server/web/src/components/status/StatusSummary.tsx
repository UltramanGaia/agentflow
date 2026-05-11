import { StatusBadge } from "./StatusBadge";

interface StatusSummaryProps {
  label: string;
  value: string | number;
  status?: string;
  hint?: string;
}

export function StatusSummary({ label, value, status, hint }: StatusSummaryProps) {
  return (
    <div className="metric-card">
      <div className="metric-label-row">
        <span className="metric-label">{label}</span>
        {status ? <StatusBadge status={status} /> : null}
      </div>
      <strong>{value}</strong>
      {hint ? <span className="metric-hint">{hint}</span> : null}
    </div>
  );
}
