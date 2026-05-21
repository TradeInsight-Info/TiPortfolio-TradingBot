import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTheme } from "./useTheme";

const mockMatchMedia = (matches) => ({
  matches,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
});

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => mockMatchMedia(false)),
  });
});

describe("useTheme", () => {
  it("applies dark class when OS prefers dark", () => {
    window.matchMedia = vi.fn().mockImplementation(() => mockMatchMedia(true));
    const { result } = renderHook(() => useTheme());
    expect(result.current.isDark).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("does not apply dark class when OS prefers light", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.isDark).toBe(false);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("toggle flips the dark class and persists to localStorage", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(result.current.isDark).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("theme")).toBe("dark");
  });

  it("reads stored theme from localStorage over OS preference", () => {
    localStorage.setItem("theme", "dark");
    window.matchMedia = vi.fn().mockImplementation(() => mockMatchMedia(false));
    const { result } = renderHook(() => useTheme());
    expect(result.current.isDark).toBe(true);
  });
});
