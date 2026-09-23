import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { aiStatusFromHealth, type ServerAiStatus } from '../features/analyze/serverStatus';

/** Whether the server can run an analysis: key configured, mock mode, or neither. */
export function useServerAiStatus(): ServerAiStatus {
  const [status, setStatus] = useState<ServerAiStatus>('checking');

  useEffect(() => {
    const controller = new AbortController();
    api
      .health(controller.signal)
      .then((health) => setStatus(aiStatusFromHealth(health)))
      .catch(() => {
        if (!controller.signal.aborted) setStatus(aiStatusFromHealth(null));
      });
    return () => controller.abort();
  }, []);

  return status;
}
