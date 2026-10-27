import { ChevronLeft, ChevronRight } from "lucide-react";

const arrowClass =
  "text-primary hover:bg-primary/5 focus-visible:outline-ring pointer-events-auto absolute top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded opacity-100 transition-[color,background-color,opacity] duration-150 group-focus-within/discovery:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-2 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/discovery:opacity-100";

export function DiscoveryNavigation({
  previousLabel,
  nextLabel,
  onPrevious,
  onNext,
}: {
  previousLabel: string;
  nextLabel: string;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <>
      <button
        type="button"
        aria-label={previousLabel}
        title={previousLabel}
        onClick={onPrevious}
        className={`${arrowClass} -left-8`}
      >
        <ChevronLeft aria-hidden="true" className="size-5" />
      </button>
      <button
        type="button"
        aria-label={nextLabel}
        title={nextLabel}
        onClick={onNext}
        className={`${arrowClass} -right-8`}
      >
        <ChevronRight aria-hidden="true" className="size-5" />
      </button>
    </>
  );
}
