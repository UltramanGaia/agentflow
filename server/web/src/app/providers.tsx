import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { createContext, useContext, useMemo, useRef, useState } from "react";

type ToastTone = "info" | "success" | "warning" | "danger";

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface ToastContextValue {
  toasts: ToastItem[];
  pushToast: (toast: Omit<ToastItem, "id">) => void;
  dismissToast: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            retry: 1,
          },
        },
      }),
  );
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextToastId = useRef(1);

  const toastValue = useMemo<ToastContextValue>(
    () => ({
      toasts,
      pushToast: (toast) => {
        const id = nextToastId.current++;
        setToasts((current) => [...current, { ...toast, id }]);
        window.setTimeout(() => {
          setToasts((current) => current.filter((item) => item.id !== id));
        }, 4200);
      },
      dismissToast: (id) => setToasts((current) => current.filter((item) => item.id !== id)),
    }),
    [toasts],
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ToastContext.Provider value={toastValue}>{children}</ToastContext.Provider>
    </QueryClientProvider>
  );
}

export function useToasts() {
  const context = useContext(ToastContext);
  return (
    context ?? {
      toasts: [],
      pushToast: () => {},
      dismissToast: () => {},
    }
  );
}
