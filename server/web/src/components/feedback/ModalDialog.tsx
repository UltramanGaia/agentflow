import type { PropsWithChildren, ReactNode } from "react";
import { useEffect } from "react";

interface ModalDialogProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  onClose: () => void;
}

export function ModalDialog({ title, description, actions, onClose, children }: PropsWithChildren<ModalDialogProps>) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div aria-modal="true" className="modal-backdrop" onClick={onClose} role="dialog">
      <div className="modal-panel panel" onClick={(event) => event.stopPropagation()}>
        <div className="section-header">
          <div>
            <h2>{title}</h2>
            {description ? <p className="section-description">{description}</p> : null}
          </div>
          <div className="toolbar">
            {actions}
            <button aria-label="Close dialog" className="icon-button" onClick={onClose} type="button">
              Close
            </button>
          </div>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
