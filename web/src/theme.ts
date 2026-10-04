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
  const paper = dark ? "#181818" : "#f7f7f8"
  const surface = dark ? "#242424" : "#ffffff"
  const border = dark ? "#737373" : "#858585"
  const divider = dark ? "#404040" : "#dddddf"
  const pencil = dark ? "#aaaaaa" : "#6b6b6b"
  const hover = dark ? "#303030" : "#eeeeee"
  const active = dark ? "#404040" : "#dddddd"
  document.documentElement.dataset.theme = dark ? "dark" : "light"
  applyMode(dark ? Mode.Dark : Mode.Light)
  applyTheme({
    theme: {
      tokens: {
        fontFamilyBase: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        colorBackgroundLayoutMain: paper,
        colorBackgroundContainerContent: surface,
        colorBackgroundContainerHeader: surface,
        colorTextBodyDefault: ink,
        colorTextBodySecondary: pencil,
        colorTextHeadingDefault: ink,
        colorTextLinkDefault: ink,
        colorTextLinkHover: ink,
        colorBorderDividerDefault: divider,
        colorBorderDividerSecondary: divider,
        colorBackgroundButtonPrimaryDefault: surface,
        colorBackgroundButtonPrimaryHover: hover,
        colorBackgroundButtonPrimaryActive: active,
        colorTextButtonPrimaryDefault: ink,
        colorTextButtonPrimaryHover: ink,
        colorTextButtonPrimaryActive: ink,
        colorBorderButtonPrimaryDefault: border,
        colorBorderButtonPrimaryHover: border,
        colorBorderButtonPrimaryActive: border,
        colorBackgroundButtonNormalDefault: surface,
        colorBackgroundInputDefault: surface,
        colorBackgroundButtonNormalHover: hover,
        colorBackgroundButtonNormalActive: active,
        colorBorderButtonNormalDefault: border,
        colorBorderButtonNormalHover: border,
        colorBorderButtonNormalActive: border,
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
        colorBorderSegmentDefault: border,
        colorBorderSegmentHover: ink,
        colorTextSegmentDefault: ink,
        colorTextSegmentHover: ink,
        colorBorderInputDefault: border,
        colorBorderInputFocused: ink,
        colorBorderItemFocused: ink,
        borderRadiusButton: "2px",
        borderRadiusContainer: "2px",
        borderRadiusInput: "2px",
      },
    },
  })
}
