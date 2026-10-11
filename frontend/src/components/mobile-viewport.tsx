"use client";

import { useEffect } from "react";

/** iOS keyboards resize the visual viewport, even when 100dvh stays unchanged. */
export function MobileViewport() {
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const mobile = window.matchMedia("(max-width: 1023px)");
    const style = document.documentElement.style;
    const clear = () => {
      style.removeProperty("--app-viewport-height");
      style.removeProperty("--app-viewport-top");
    };
    const update = () => {
      if (!mobile.matches) {
        clear();
        return;
      }
      // Preserve pinch zoom: do not reflow the interface as the user zooms.
      if (viewport.scale !== 1) return;
      style.setProperty("--app-viewport-height", `${viewport.height}px`);
      style.setProperty("--app-viewport-top", `${viewport.offsetTop}px`);
    };
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    mobile.addEventListener("change", update);
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
      mobile.removeEventListener("change", update);
      clear();
    };
  }, []);

  return null;
}
