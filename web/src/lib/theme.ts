// Light/dark theme: a `.dark` class on <html>, remembered in localStorage; light unless a choice was saved.
import { createContext, createElement, useContext, useLayoutEffect, useState, type ReactNode } from "react"

export type Theme = "light" | "dark"

// index.html repeats this key and the default below in an inline script that runs before the bundle.
const STORAGE_KEY = "brightlearn.theme"

// Storage can be blocked (private windows, cleared site data), so every access is guarded.
function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value === "light" || value === "dark" ? value : null
  } catch {
    return null
  }
}

function saveTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Not remembered this time; the toggle still works for the page's lifetime.
  }
}

function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark")
}

// Light by default, as NotebookLM opens; the OS preference is not consulted.
function initialTheme(): Theme {
  return storedTheme() ?? "light"
}

type ThemeValue = { theme: Theme; setTheme: (theme: Theme) => void }

const ThemeContext = createContext<ThemeValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(initialTheme)
  useLayoutEffect(() => applyTheme(theme), [theme])
  // Only an explicit choice is saved; a visitor who never toggles gets light every time.
  const setTheme = (next: Theme) => {
    saveTheme(next)
    setThemeState(next)
  }
  return createElement(ThemeContext.Provider, { value: { theme, setTheme } }, children)
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext)
  if (!value) throw new Error("useTheme must be used inside <ThemeProvider>")
  return value
}
