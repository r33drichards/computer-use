// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest"

vi.mock("@cloudscape-design/components/theming", () => ({ applyTheme: vi.fn() }))
vi.mock("@cloudscape-design/global-styles", () => ({ applyMode: vi.fn(), Mode: { Dark: "dark", Light: "light" } }))

beforeEach(() => {
  vi.resetModules()
  localStorage.clear()
})

it("defaults to System and follows device changes, while explicit choices override them", async () => {
  let dark = false
  let changed = () => {}
  vi.stubGlobal("matchMedia", () => ({
    get matches() { return dark },
    addEventListener: (_: string, callback: () => void) => { changed = callback },
  }))
  const theme = await import("./theme")
  theme.initializeTheme()
  expect(theme.getThemePreference()).toBe("system")
  expect(document.documentElement.dataset.theme).toBe("light")
  dark = true
  changed()
  expect(document.documentElement.dataset.theme).toBe("dark")
  theme.setThemePreference("light")
  changed()
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(localStorage.getItem("computer-use-theme")).toBe("light")
  theme.setThemePreference("system")
  expect(document.documentElement.dataset.theme).toBe("dark")
})

it("restores a saved dark preference", async () => {
  localStorage.setItem("computer-use-theme", "dark")
  const theme = await import("./theme")
  theme.applyWireframeTheme()
  expect(document.documentElement.dataset.theme).toBe("dark")
})
