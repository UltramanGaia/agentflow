import type { PropsWithChildren } from "react";

type Tone = "info" | "success" | "warning" | "danger";

export function InlineNotice({ children, tone = "info" }: PropsWithChildren<{ tone?: Tone }>) {
  return <div className={`inline-notice tone-${tone}`}>{children}</div>;
}
