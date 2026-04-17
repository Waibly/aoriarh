"use client";

export function ThinkingIndicator() {
  return (
    <div className="flex flex-col items-start">
      <div
        className="flex items-center gap-1.5 px-1 py-2"
        role="status"
        aria-live="polite"
        aria-label="Recherche en cours"
      >
        <span
          className="inline-block size-2 rounded-full bg-[#652bb0] animate-[bounce-dot_1s_ease-in-out_infinite]"
        />
        <span
          className="inline-block size-2 rounded-full bg-[#652bb0] animate-[bounce-dot_1s_ease-in-out_infinite]"
          style={{ animationDelay: "0.15s" }}
        />
        <span
          className="inline-block size-2 rounded-full bg-[#652bb0] animate-[bounce-dot_1s_ease-in-out_infinite]"
          style={{ animationDelay: "0.3s" }}
        />
      </div>
    </div>
  );
}
