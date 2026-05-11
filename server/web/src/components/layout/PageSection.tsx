import type { PropsWithChildren, ReactNode } from "react";

interface PageSectionProps {
  title?: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}

export function PageSection({ title, description, actions, className, children }: PropsWithChildren<PageSectionProps>) {
  return (
    <section className={`panel section-panel${className ? ` ${className}` : ""}`}>
      {(title || description || actions) ? (
        <div className="section-header">
          <div>
            {title ? <h2>{title}</h2> : null}
            {description ? <p className="section-description">{description}</p> : null}
          </div>
          {actions ? <div className="toolbar">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
