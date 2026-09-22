import { useCallback, useEffect, useState } from 'react'

export type Theme = 'system' | 'light' | 'dark'

const KEY = 'clearview.theme'
export const THEMES: { value: Theme; label: string; hint: string }[] = [
  { value: 'system', label: 'Match system', hint: 'Follows your OS appearance setting' },
  { value: 'light', label: 'Light', hint: 'Always light, regardless of the OS' },
  { value: 'dark', label: 'Dark', hint: 'Always dark, regardless of the OS' },
]

/** localStorage throws in private windows and when site data is blocked. */
function read(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    /* fall through to the default */
  }
  return 'light'
}

function write(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* a remembered preference is a convenience, not a requirement */
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
}

/** Resolve 'system' to what is actually on screen right now. */
export function effectiveTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

// Run at import, before React paints, so the page never flashes the wrong theme.
applyTheme(read())

export function useTheme(): [Theme, (t: Theme) => void, 'light' | 'dark'] {
  const [theme, setTheme] = useState<Theme>(read)
  const [resolved, setResolved] = useState<'light' | 'dark'>(() => effectiveTheme(read()))

  const choose = useCallback((next: Theme) => {
    setTheme(next)
    write(next)
    applyTheme(next)
    setResolved(effectiveTheme(next))
  }, [])

  // While on 'system', track the OS flipping (e.g. at sunset) without a reload.
  useEffect(() => {
    if (theme !== 'system' || !window.matchMedia) return
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    const sync = () => setResolved(mq.matches ? 'light' : 'dark')
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [theme])

  return [theme, choose, resolved]
}
