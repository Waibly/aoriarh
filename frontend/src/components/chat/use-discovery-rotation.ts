"use client";

import { useCallback, useEffect, useState } from "react";

export function useDiscoveryRotation(suspended: boolean) {
  const [step, setStep] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pageHidden, setPageHidden] = useState(false);
  const next = useCallback(() => setStep((value) => value + 1), []);
  const previous = useCallback(() => setStep((value) => value - 1), []);

  useEffect(() => {
    const updateVisibility = () => setPageHidden(document.hidden);
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches)
      setPaused(true);
    return () =>
      document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    if (paused || hovered || focused || pageHidden || suspended) return;
    const timer = window.setTimeout(next, 5_000);
    return () => window.clearTimeout(timer);
  }, [step, paused, hovered, focused, pageHidden, suspended, next]);

  return {
    step,
    setStep,
    paused,
    next,
    previous,
    togglePause: () => setPaused((value) => !value),
    interactionProps: {
      onMouseEnter: () => setHovered(true),
      onMouseLeave: () => setHovered(false),
      onFocusCapture: () => setFocused(true),
      onBlurCapture: (event: React.FocusEvent<HTMLElement>) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          setFocused(false);
      },
    },
  };
}
