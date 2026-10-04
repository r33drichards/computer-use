import { applyTheme } from "@cloudscape-design/components/theming"

import { applyMode, Mode } from "@cloudscape-design/global-styles"

export type ThemePreference = "light" | "dark" | "system"
const storageKey = "computer-use-theme"
function readThemePreference(): ThemePreference {
  try {
    const value = localStorage.getItem(storageKey)
    if (value === "light" || value === "dark") return value
  } catch { /* Storage may be disabled. */ }
  return "system"
}
export function setThemePreference(value: ThemePreference) {
  try { localStorage.setItem(storageKey, value) } catch { /* Still apply this session. */ }
  preference = value
  applyWireframeTheme()
  window.dispatchEvent(new Event("themechange"))
}
let preference = readThemePreference()
export function getThemePreference(): ThemePreference { return preference }
export function isDarkTheme() {
  return preference === "dark" || (preference === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches === true)
}
export function initializeTheme() {
  applyWireframeTheme()
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (preference === "system") {
      applyWireframeTheme()
      window.dispatchEvent(new Event("themechange"))
    }
  })
  window.addEventListener("storage", event => {
    if (event.key === storageKey || event.key === null) {
      preference = readThemePreference()
      applyWireframeTheme()
      window.dispatchEvent(new Event("themechange"))
    }
  })
}

export function applyWireframeTheme() {
  const dark = isDarkTheme()
  const ink = dark ? "#eeeeee" : "#111111"
  const paper = dark ? "#181818" : "#ffffff"
  const pencil = dark ? "#aaaaaa" : "#6b6b6b"
  const hover = dark ? "#303030" : "#eeeeee"
  const active = dark ? "#404040" : "#dddddd"
  document.documentElement.dataset.theme = dark ? "dark" : "light"
  applyMode(dark ? Mode.Dark : Mode.Light)
  applyTheme({
    theme: {
      tokens: {
        fontFamilyBase: '"Comic Neue", "Chalkboard SE", "Comic Sans MS", "Segoe Print", cursive',
        colorBackgroundLayoutMain: paper,
        colorBackgroundContainerContent: paper,
        colorBackgroundContainerHeader: paper,
        colorTextBodyDefault: ink,
        colorTextBodySecondary: pencil,
        colorTextHeadingDefault: ink,
        colorTextLinkDefault: ink,
        colorTextLinkHover: ink,
        colorBorderDividerDefault: ink,
        colorBorderDividerSecondary: pencil,
        colorBackgroundButtonPrimaryDefault: paper,
        colorBackgroundButtonPrimaryHover: hover,
        colorBackgroundButtonPrimaryActive: active,
        colorTextButtonPrimaryDefault: ink,
        colorTextButtonPrimaryHover: ink,
        colorTextButtonPrimaryActive: ink,
        colorBorderButtonPrimaryDefault: ink,
        colorBorderButtonPrimaryHover: ink,
        colorBorderButtonPrimaryActive: ink,
        colorBackgroundButtonNormalHover: hover,
        colorBackgroundButtonNormalActive: active,
        colorBorderButtonNormalDefault: ink,
        colorBorderButtonNormalHover: ink,
        colorBorderButtonNormalActive: ink,
        colorTextButtonNormalDefault: ink,
        colorTextButtonNormalHover: ink,
        colorTextButtonNormalActive: ink,
        colorBackgroundControlChecked: ink,
        // Tabs, alerts, flash messages and selected items: ink on paper, like the rest.
        colorTextAccent: ink,
        colorBorderItemSelected: ink,
        colorBackgroundItemSelected: hover,
        colorTextStatusInfo: ink,
        colorTextStatusError: ink,
        colorTextStatusSuccess: ink,
        colorTextStatusWarning: ink,
        colorBorderStatusInfo: ink,
        colorBorderStatusError: ink,
        colorBorderStatusSuccess: ink,
        colorBorderStatusWarning: ink,
        colorBackgroundStatusInfo: paper,
        colorBackgroundStatusError: paper,
        colorBackgroundStatusSuccess: paper,
        colorBackgroundStatusWarning: paper,
        colorBackgroundNotificationBlue: paper,
        colorBackgroundNotificationGreen: paper,
        colorBackgroundNotificationRed: paper,
        colorBackgroundNotificationYellow: paper,
        colorTextNotificationDefault: ink,
        colorTextNotificationYellow: ink,
        colorBackgroundSegmentActive: ink,
        colorBorderSegmentActive: ink,
        colorBorderSegmentDefault: ink,
        colorBorderSegmentHover: ink,
        colorTextSegmentDefault: ink,
        colorTextSegmentHover: ink,
        colorBorderInputDefault: ink,
        colorBorderInputFocused: ink,
        colorBorderItemFocused: ink,
        borderRadiusButton: "2px",
        borderRadiusContainer: "2px",
        borderRadiusInput: "2px",
      },
    },
  })
}
