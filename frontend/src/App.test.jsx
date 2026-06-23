import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";

beforeEach(() => {
  // jsdom lacks matchMedia, which useTheme reads on mount.
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  // jsdom lacks IntersectionObserver, used by the nav scroll-spy effect.
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // All data hooks fetch on mount; return empty so the app degrades gracefully.
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
  );
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("footer credits Tim B (Maintainer, GitHub) and Vicky Chang (Developer, LinkedIn)", async () => {
  render(<App />);

  const tim = await screen.findByRole("link", { name: "Tim B" });
  expect(tim.getAttribute("href")).toBe("https://github.com/tim-hub");

  const vicky = screen.getByRole("link", { name: "Vicky Chang" });
  expect(vicky.getAttribute("href")).toBe(
    "https://www.linkedin.com/in/vicky-chang-vc95/"
  );

  expect(screen.getByText("Maintainer")).toBeTruthy();
  expect(screen.getByText("Developer")).toBeTruthy();
});
