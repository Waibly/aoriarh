"use client";

import { useEffect } from "react";

/** Guard explicit navigation while an editor contains unsaved user input. */
export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const leave = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const guard = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const navigation =
        event.type === "pointerdown"
          ? target.closest('[data-slot="sheet-overlay"]')
          : event.type === "keydown"
            ? (event as KeyboardEvent).key === "Escape"
            : target.closest(
                'a[href], [role="tab"], [data-slot="sheet-close"]'
              );
      if (!navigation) return;
      if (
        !window.confirm(
          "Abandonner les modifications non enregistrées ? Annuler permet de continuer la saisie."
        )
      ) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
      }
    };
    window.addEventListener("beforeunload", leave);
    window.addEventListener("click", guard, true);
    window.addEventListener("pointerdown", guard, true);
    window.addEventListener("keydown", guard, true);
    return () => {
      window.removeEventListener("beforeunload", leave);
      window.removeEventListener("click", guard, true);
      window.removeEventListener("pointerdown", guard, true);
      window.removeEventListener("keydown", guard, true);
    };
  }, [dirty]);
}
