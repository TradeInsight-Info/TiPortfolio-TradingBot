# Style Alignment with tradeinsight.info + TiPortfolio Branding

**Status:** Draft for review
**Date:** 2026-05-21
**Scope:** `frontend/` directory of TiPortfolio-TradingBot

## Goal

1. Align the TiPortfolio demo site (`frontend/`) visually with the parent product `tradeinsight.info` (`tradeinsight-next`) so the two feel like one product family.
2. Give TiPortfolio its own logo and complete favicon set, derived from the parent brand mark but visually distinct.

**Success criteria:**

- Visiting the TiPortfolio demo feels like a sibling of tradeinsight.info — same emerald accent, same border radius, same typography weight hierarchy, same surface treatment.
- Logo renders cleanly at 16px favicon and 1200×630 OG card.
- No daisyUI classes remain in the codebase; no daisyUI plugin in build output.
- Dark mode toggles via the same `.dark` class convention as tradeinsight-next.

---

## Current state (audit)

### tradeinsight-next (reference)

- Next.js 15, Tailwind v3, custom `tailwind.config.ts`, shadcn/ui pattern.
- Design tokens in `src/app/globals.css` as HSL CSS variables under `:root` and `.dark`.
- Primary colour: emerald-8 `#065f46` (light mode), emerald-300 `hsl(156.2 71.6% 66.9%)` (dark mode).
- Border radius: `--radius: 1rem` (noticeably rounded).
- Brand mark: rounded-square logo `public/static/pelosi_trade_logo.svg` — green `#1bb680` fill, white capitol-silhouette icon, rising chart-line motif.
- Favicon set: `public/static/favicon/{favicon.ico, favicon.png, favicon.webp}`.

### TiPortfolio frontend (target)

- Vite 8, React 19, **Tailwind v4** (`@tailwindcss/vite`), **daisyUI 5**.
- `src/index.css` is two `@import` lines — no design tokens, no theme customisation.
- Three components: `IntroSection.jsx`, `DeltaTable.jsx`, `BenchmarkChart.jsx`.
- All components use daisyUI classes: `btn btn-primary`, `navbar`, `bg-base-100`, `text-base-content`.
- No `public/` folder, no favicon, no logo.

---

## Design

### Section 1 — Token system (Tailwind v4)

Replace `frontend/src/index.css` wholesale with a Tailwind v4 `@theme` block that mirrors the HSL variables from tradeinsight-next.

**Why Tailwind v4 differs from v3:** In v4 there is no `tailwind.config.ts` — theme tokens live in CSS via `@theme` inline variables. The class names (`bg-primary`, `text-muted-foreground`) work identically once the `@theme` block maps them.

```css
@import "tailwindcss";

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 240 10% 3.9%;
    --card: 0 0% 100%;
    --card-foreground: 240 10% 3.9%;
    --primary: 163.1 88.1% 19.8%;          /* emerald-8 #065f46 */
    --primary-foreground: 356 100% 100%;
    --secondary: 240 4.8% 95.9%;
    --secondary-foreground: 240 5.9% 10%;
    --muted: 240 4.8% 95.9%;
    --muted-foreground: 240 3.8% 46.1%;
    --accent: 240 4.8% 95.9%;
    --accent-foreground: 240 5.9% 10%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 5.9% 90%;
    --input: 240 5.9% 90%;
    --ring: 161.4 93.5% 30.4%;
    --radius: 1rem;
    --chart-1: 0 84.2% 60.2%;              /* red */
    --chart-2: 161.4 93.5% 30.4%;          /* forest green */
    --chart-3: 197 37% 24%;                /* deep blue-cyan */
    --chart-4: 43 74% 66%;                 /* golden yellow */
    --chart-5: 27 87% 67%;                 /* orange */
  }

  .dark {
    --background: 20 14.3% 4.1%;
    --foreground: 0 0% 95%;
    --card: 24 9.8% 10%;
    --card-foreground: 0 0% 95%;
    --primary: 156.2 71.6% 66.9%;          /* emerald-300 */
    --primary-foreground: 165.7 91.3% 9%;
    --secondary: 240 3.7% 15.9%;
    --secondary-foreground: 0 0% 98%;
    --muted: 0 0% 15%;
    --muted-foreground: 240 5% 64.9%;
    --accent: 12 6.5% 15.1%;
    --accent-foreground: 0 0% 98%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 0 85.7% 97.3%;
    --border: 240 3.7% 15.9%;
    --input: 240 3.7% 15.9%;
    --ring: 162.9 93.5% 24.3%;
    --chart-2: 160 60% 45%;
    --chart-3: 30 80% 55%;
    --chart-4: 280 65% 60%;
    --chart-5: 340 75% 55%;
  }
}

@theme {
  --color-background: hsl(var(--background));
  --color-foreground: hsl(var(--foreground));
  --color-card: hsl(var(--card));
  --color-card-foreground: hsl(var(--card-foreground));
  --color-primary: hsl(var(--primary));
  --color-primary-foreground: hsl(var(--primary-foreground));
  --color-secondary: hsl(var(--secondary));
  --color-secondary-foreground: hsl(var(--secondary-foreground));
  --color-muted: hsl(var(--muted));
  --color-muted-foreground: hsl(var(--muted-foreground));
  --color-accent: hsl(var(--accent));
  --color-accent-foreground: hsl(var(--accent-foreground));
  --color-destructive: hsl(var(--destructive));
  --color-border: hsl(var(--border));
  --color-input: hsl(var(--input));
  --color-ring: hsl(var(--ring));
  --color-chart-1: hsl(var(--chart-1));
  --color-chart-2: hsl(var(--chart-2));
  --color-chart-3: hsl(var(--chart-3));
  --color-chart-4: hsl(var(--chart-4));
  --color-chart-5: hsl(var(--chart-5));
  --radius-lg: var(--radius);
  --radius-md: calc(var(--radius) - 2px);
  --radius-sm: calc(var(--radius) - 4px);
}

html { scroll-behavior: smooth; }
body { @apply bg-background text-foreground; }
```

### Section 2 — Remove daisyUI

- Delete `@import "daisyui/daisyui.css"` from `src/index.css` (entire file is replaced above).
- Remove `daisyui` from `frontend/package.json` devDependencies and run `pnpm install`.

### Section 3 — Component class migration

Three components, surgical replacements only:

| daisyUI class | Replacement |
|---|---|
| `btn btn-primary` | `inline-flex items-center justify-center rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 transition-colors` |
| `btn btn-outline` | `inline-flex items-center justify-center rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors` |
| `navbar bg-base-100 shadow` | `flex items-center bg-card text-card-foreground border-b border-border shadow-sm px-6 gap-4 sticky top-0 z-50` |
| `text-base-content` | `text-foreground` |
| `text-gray-500` / `text-gray-600` | `text-muted-foreground` |

**Touched files:**

- `frontend/src/App.jsx` — nav classes, dark mode `<html>` toggle
- `frontend/src/components/IntroSection.jsx` — button classes
- `frontend/src/components/DeltaTable.jsx` — table surface (grep and replace)
- `frontend/src/components/BenchmarkChart.jsx` — stroke colours should use `var(--chart-2)` (Bot), `var(--chart-3)` (SPY), `var(--chart-1)` (QQQ) so they follow the dark/light palette

### Section 4 — Dark mode

Add a `useTheme` hook (`frontend/src/hooks/useTheme.js`) that:
1. Reads `localStorage.getItem('theme')` on mount; falls back to `window.matchMedia('(prefers-color-scheme: dark)')`.
2. Syncs `document.documentElement.classList.toggle('dark', isDark)`.
3. Exposes `{ isDark, toggle }` for future use.

Call it once in `App.jsx` — no toggle UI required in v1 (system preference only).

### Section 5 — Logo design

**Visual concept:** Lowercase-and-uppercase monogram **"Ti"** inside a rounded square. The "i" dot is replaced by a small upward-facing bar (accent), and a faint diagonal line ascends left-to-right behind the letters — echoing the rising-line motif in the parent `pelosi_trade_logo.svg`.

**Brand colours used:**

| Role | Hex | Source |
|---|---|---|
| Square background | `#065f46` | emerald-8 (light primary) |
| Glyph fill | `#ffffff` | white |
| Accent / dot replacement | `#6ee7b7` | emerald-300 (dark primary) |
| Diagonal line | `#6ee7b7` @ 35% opacity | emerald-300 tinted |

**SVG construction (`logo.svg`, 256×256):**

```
<rect x="0" y="0" width="256" height="256" rx="40" fill="#065f46"/>
<!-- faint rising diagonal -->
<line x1="40" y1="200" x2="216" y2="72" stroke="#6ee7b7" stroke-width="12"
      stroke-linecap="round" opacity="0.35"/>
<!-- "T" glyph — converted to path, Inter Bold 140px -->
<path d="…" fill="#ffffff"/>
<!-- "i" body — converted to path -->
<path d="…" fill="#ffffff"/>
<!-- "i" dot replaced with emerald bar -->
<rect x="152" y="58" width="20" height="20" rx="4" fill="#6ee7b7"/>
```

Glyphs MUST be converted to paths before shipping (no font dependency in the SVG).

**Assets to produce:**

| Asset | Size | Location |
|---|---|---|
| `logo.svg` | 256×256 vb | `frontend/public/logo.svg` |
| `logo-dark.svg` | 256×256 vb | `frontend/public/logo-dark.svg` — white bg, emerald-8 glyph |
| `logo-mono.svg` | 256×256 vb | `frontend/public/logo-mono.svg` — `currentColor` only |
| `wordmark.svg` | variable | `frontend/public/wordmark.svg` — monogram + "TiPortfolio" text paths |
| `favicon.ico` | 16/32/48 multi-res | `frontend/public/favicon.ico` |
| `favicon-16.png` | 16×16 | `frontend/public/favicon-16.png` |
| `favicon-32.png` | 32×32 | `frontend/public/favicon-32.png` |
| `icon-192.png` | 192×192 | `frontend/public/icon-192.png` |
| `icon-512.png` | 512×512 | `frontend/public/icon-512.png` |
| `apple-touch-icon.png` | 180×180 | `frontend/public/apple-touch-icon.png` — no transparency |
| `og-image.png` | 1200×630 | `frontend/public/og-image.png` — logo left, wordmark, tagline |

**Small-size simplification for favicons ≤ 32px:** drop the diagonal line and emerald dot accent; render only the white "Ti" monogram on the emerald-8 square with rx proportional to size.

### Section 6 — index.html meta tags

Update `frontend/index.html` `<head>` to add:

```html
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
<link rel="icon" href="/favicon-16.png" type="image/png" sizes="16x16">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#065f46">
<meta property="og:image" content="/og-image.png">
<meta property="og:title" content="TiPortfolio — ETF portfolio optimisation, paper-traded live">
<meta property="og:description" content="A live paper-trading bot that runs weekly ETF rebalances, benchmarked against SPY and QQQ.">
```

### Section 7 — Nav logo placement

Replace the plain `"TiPortfolio Demo"` text span in `App.jsx` nav with:

```jsx
<a href="#intro" className="flex items-center gap-2 mr-6">
  <img src="/logo.svg" alt="" className="h-8 w-8 rounded-md" aria-hidden="true" />
  <span className="text-lg font-bold">TiPortfolio</span>
</a>
```

---

## Non-goals

- No shadcn/ui component library installation — adopt the token system only, not Radix components.
- No port of tradeinsight-next features (i18n, MDX, sidebar, auth).
- No manual light/dark toggle UI in v1 — system preference is sufficient for a demo site.
- No visual redesign of the chart (Recharts) beyond swapping stroke colours to CSS vars.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Tailwind v4 `@theme` syntax is different from v3 config | Use the explicit translation block in Section 1 exactly; verify `bg-primary` resolves in `pnpm dev`. |
| Missed daisyUI class after migration | Grep for `btn\|navbar\|base-100\|base-content\|daisyui` after migration; fix each hit. |
| Logo glyph rendering depends on installed font | Convert all text glyphs to paths before committing SVGs. |
| Favicon loses detail at 16px | Ship simplified ICO (monogram only, no diagonal or accent dot). |

---

## Acceptance checks

1. `pnpm dev` runs; no daisyUI import in output bundle.
2. `grep -r "btn-\|navbar\|base-100\|base-content\|daisyui" frontend/src` → zero matches.
3. Buttons render emerald-8 background (light) / emerald-300 (dark).
4. Cards and buttons have visible `1rem` border radius.
5. Favicon visible in browser tab (all major browsers).
6. Sharing the URL on Slack/iMessage shows the OG image preview.
7. Side-by-side with tradeinsight.info — same emerald accent, same rounding, same weight hierarchy.
