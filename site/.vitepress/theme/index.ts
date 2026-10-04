import { h } from "vue"
import ThemeSettings from "./ThemeSettings.vue"
import type { Theme } from "vitepress"
// No bundled web font: system fonts only.
import DefaultTheme from "vitepress/theme-without-fonts"
import BlogIndex from "./BlogIndex.vue"
import "./custom.css"

export default {
  extends: DefaultTheme,
  Layout: () => h(DefaultTheme.Layout, null, {
    "nav-bar-content-after": () => h(ThemeSettings, { class: "theme-desktop" }),
    "nav-screen-content-after": () => h(ThemeSettings),
  }),
  enhanceApp({ app }) {
    app.component("BlogIndex", BlogIndex)
  },
} satisfies Theme
