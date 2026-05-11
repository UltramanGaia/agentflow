import { useToasts } from "../../app/providers";

export function ToastRegion() {
  const { toasts, dismissToast } = useToasts();

  return (
    <div aria-live="polite" className="toast-region">
      {toasts.map((toast) => (
        <div className={`toast tone-${toast.tone}`} key={toast.id} role="status">
          <div className="toast-copy">
            <strong>{toast.title}</strong>
            {toast.description ? <span>{toast.description}</span> : null}
          </div>
          <button className="icon-button" onClick={() => dismissToast(toast.id)} type="button">
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
