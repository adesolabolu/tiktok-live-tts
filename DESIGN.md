# Design System: Pure Black Streamer Hardware Studio

## 1. Aesthetic Direction
- **Identity:** High-precision, zero-noise pro audio broadcast studio.
- **Canvas:** Pure Pitch Black (`#000000`), zero navy/blue tint.
- **Card Surfaces:** Deep Onyx (`#09090b` / `#0f0f11`) with micro-hairline borders.
- **Elevated Surfaces:** Surface popover/modal (`#141416`).
- **Typography:** Display & Sans (`Plus Jakarta Sans`, `Inter`, system-ui), Telemetry & Badges (`JetBrains Mono`, monospace).

## 2. Color Palette
```yaml
colors:
  canvas: "#000000"              # Absolute pitch black canvas
  surface-ground: "#050506"       # Deepest ground layer
  surface-card: "#0a0a0c"         # Card background
  surface-card-hover: "#111114"   # Card hover state
  surface-elevated: "#161619"     # Popovers, tooltips, dialogs
  
  border-subtle: "#1c1c20"        # 1px hairline border
  border-hover: "#2a2a30"         # Focused/hovered border
  border-active: "#38bdf8"        # Active state cyan highlight
  
  text-primary: "#ffffff"         # Crisp 100% white
  text-secondary: "#a1a1aa"       # High-legibility neutral gray
  text-muted: "#52525b"           # Subtle metadata captions
  
  accent-cyan: "#38bdf8"          # Laser cyan (telemetry, live audio waves)
  accent-cyan-glow: "rgba(56, 189, 248, 0.2)"
  accent-tiktok: "#fe2c55"        # TikTok crimson (subtle stream accent)
  accent-green: "#10b981"         # Live status indicator
  
  button-primary-bg: "#ffffff"    # Pure high-contrast white pill
  button-primary-fg: "#000000"    # Black text on white
  button-primary-hover: "#eaeaea"
```

## 3. Elevation & Radii
- **Card Radius:** `12px` (tactile hardware feel, not overly bubbly)
- **Button Radius:** `9999px` (pill) for primary CTAs, `8px` for action controls
- **Hairlines:** `1px solid var(--border-subtle)`
- **Shadows:** No heavy diffuse drop shadows; subtle inner edge highlight:
  `box-shadow: inset 0 1px 0 0 rgba(255, 255, 255, 0.05), 0 8px 32px -8px rgba(0, 0, 0, 0.8)`

## 4. Motion & Tactility
- **Button Click:** `active:scale-[0.97]` with `cubic-bezier(0.16, 1, 0.3, 1)` transition `120ms`
- **Audio Equalizer:** Pure CSS keyframed soundwave bars simulating live voice activity
- **Reveal:** Single deliberate page entrance sequence, zero tacky scroll animations
