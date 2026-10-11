import { render } from "@testing-library/react";
import { MobileViewport } from "@/components/mobile-viewport";

describe("MobileViewport", () => {
  const originalViewport = Object.getOwnPropertyDescriptor(window, "visualViewport");
  const originalMatchMedia = window.matchMedia;
  let viewport: EventTarget & { height: number; offsetTop: number; scale: number };
  let media: EventTarget & { matches: boolean };
  const height = () => document.documentElement.style.getPropertyValue("--app-viewport-height");

  beforeEach(() => {
    viewport = Object.assign(new EventTarget(), { height: 812, offsetTop: 0, scale: 1 });
    media = Object.assign(new EventTarget(), { matches: true });
    Object.defineProperty(window, "visualViewport", { configurable: true, value: viewport });
    window.matchMedia = jest.fn().mockReturnValue(media);
  });

  afterEach(() => {
    if (originalViewport) Object.defineProperty(window, "visualViewport", originalViewport);
    else Reflect.deleteProperty(window, "visualViewport");
    window.matchMedia = originalMatchMedia;
  });

  it("follows the visible height and offset when the keyboard opens", () => {
    const { unmount } = render(<MobileViewport />);
    expect(height()).toBe("812px");
    viewport.height = 360;
    viewport.offsetTop = 40;
    viewport.dispatchEvent(new Event("resize"));
    expect(height()).toBe("360px");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("40px");
    unmount();
    expect(height()).toBe("");
    viewport.dispatchEvent(new Event("resize"));
    expect(height()).toBe("");
  });

  it("preserves layout during pinch zoom and restores native desktop sizing", () => {
    render(<MobileViewport />);
    viewport.scale = 2;
    viewport.height = 406;
    viewport.dispatchEvent(new Event("resize"));
    expect(height()).toBe("812px");
    media.matches = false;
    media.dispatchEvent(new Event("change"));
    expect(height()).toBe("");
  });

  it("uses CSS viewport sizing when VisualViewport is unavailable", () => {
    Object.defineProperty(window, "visualViewport", { configurable: true, value: undefined });
    render(<MobileViewport />);
    expect(height()).toBe("");
  });
});
