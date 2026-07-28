import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface Entitlement {
  state: string;
  edition: string;
  valid: boolean;
  mutations_allowed: boolean;
  reason: string;
  major_version: number | null;
  max_active_projects: number | null;
  trial_days_remaining: number;
  trial_expires_at: string | null;
}

const unavailable: Entitlement = {
  state: "extraction",
  edition: "unpaid",
  valid: false,
  mutations_allowed: false,
  reason: "unavailable",
  major_version: null,
  max_active_projects: 0,
  trial_days_remaining: 0,
  trial_expires_at: null,
};

export function useEntitlement() {
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const requestSequence = useRef(0);

  const refreshEntitlement = useCallback(async () => {
    const sequence = ++requestSequence.current;
    try {
      const authoritative = await api.getEntitlement();
      if (sequence === requestSequence.current) setEntitlement(authoritative);
      return authoritative;
    } catch (error) {
      if (sequence === requestSequence.current) setEntitlement(unavailable);
      throw error;
    }
  }, []);

  useEffect(() => {
    void refreshEntitlement().catch(() => undefined);
    return window.growthmapDesktop?.entitlement.onChanged(() => {
      // The event is only invalidation. Never trust renderer/IPC event data for authorization.
      void refreshEntitlement().catch(() => undefined);
    });
  }, [refreshEntitlement]);

  return { entitlement, refreshEntitlement };
}
