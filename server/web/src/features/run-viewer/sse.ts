import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useEffectEvent } from "react";

export function useRunStream(runId: string | undefined) {
  const queryClient = useQueryClient();
  const onEvent = useEffectEvent(() => {
    if (!runId) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: ["run-detail", runId] });
    void queryClient.invalidateQueries({ queryKey: ["runs"] });
  });

  useEffect(() => {
    if (!runId) {
      return;
    }
    const source = new EventSource(`/api/runs/${runId}/stream`);
    source.addEventListener("event", onEvent);
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.close();
    };
  }, [onEvent, runId]);
}
