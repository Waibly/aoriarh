"use client";
import { useCallback, useState, type Dispatch, type SetStateAction } from "react";
import { reportIncident } from "@/lib/incidents";

/** Same state/rendered value, plus technical notification. Never sends the value. */
export function useErrorState<T>(initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState(initial);
  const reportAndSet = useCallback<Dispatch<SetStateAction<T>>>((next) => {
    // Updater functions retain React semantics and are not evaluated for telemetry.
    if (typeof next !== "function" && next !== null && next !== undefined && next !== "" && next !== false) {
      reportIncident("ui_error");
    }
    setValue(next);
  }, []);
  // Third setter renders an error already reported at its technical origin.
  return [value, reportAndSet, setValue];
}
