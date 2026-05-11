import type { PropsWithChildren, ReactNode } from "react";

interface SplitPaneProps {
  aside: ReactNode;
  className?: string;
  asideClassName?: string;
  mainClassName?: string;
}

export function SplitPane({
  aside,
  className,
  asideClassName,
  mainClassName,
  children,
}: PropsWithChildren<SplitPaneProps>) {
  return (
    <div className={`split-pane${className ? ` ${className}` : ""}`}>
      <div className={`split-pane-main${mainClassName ? ` ${mainClassName}` : ""}`}>{children}</div>
      <aside className={`split-pane-aside${asideClassName ? ` ${asideClassName}` : ""}`}>{aside}</aside>
    </div>
  );
}
