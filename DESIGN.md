---
name: BoudyOS
description: Focused personal Telegram workspace interface
colors:
  canvas: "#050b1d"
  surface: "#0d1d46"
  primary: "#2670ff"
  accent-cyan: "#28d8f5"
  text: "#f5f9ff"
  text-muted: "#c3d4f0"
typography:
  body:
    fontFamily: "Telegram system sans, Noto Sans, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Noto Sans, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.08em"
rounded:
  sm: "8px"
  md: "16px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  dashboard-surface:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "native Telegram message inset"
  primary-action:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "native Telegram inline-button padding"
  accent-action:
    backgroundColor: "{colors.accent-cyan}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.sm}"
    padding: "native Telegram inline-button padding"
---

# Design System: BoudyOS

## Overview

**Creative North Star: "The focused control surface"**

BoudyOS is operated inside Telegram, so the design system works with Telegram's native messages, inline keyboards, links, and back navigation instead of pretending the product is a web dashboard. The interface should feel like a calm command surface: a short overview establishes context, grouped actions expose the most useful capabilities, and progressive disclosure keeps plugin and settings detail one step away.

The visual identity is anchored by the existing BoudyOS mark: a blue-to-cyan terminal-shaped B on a deep navy field. The new inline banner extends that identity with a restrained technical grid and a framed logo panel. The banner is supporting context, never a substitute for readable labels or status text.

**Key Characteristics:**
- Telegram-native, text-labeled controls with stable back and dashboard exits.
- Deep navy surfaces with one electric blue primary and cyan accent.
- BoudyOS language in user-facing copy; upstream provenance remains in license and technical documentation only.
- Bundled, deterministic media by default; configured remote media remains an explicit override.

## Colors

The palette is a dark operating surface with high-contrast cool text and a single blue/cyan signal system.

### Primary
- **Electric workspace blue** (#2670ff): primary navigation emphasis and active system actions.
- **Terminal cyan** (#28d8f5): brand accent, small labels, rules, and visual focus in authored imagery.

### Neutral
- **Deep navy canvas** (#050b1d): authored banner background and the visual anchor for the mark.
- **Navy surface** (#0d1d46): secondary layer used to separate operational groups in imagery.
- **Signal white** (#f5f9ff): headings and high-priority copy.
- **Cool mist** (#c3d4f0): supporting copy that remains readable against the dark canvas.

**The One Signal Rule.** Blue and cyan indicate brand or action. Do not scatter bright color across inactive labels or decorative copy.

## Typography

**Display Font:** Noto Sans Bold (with the Telegram system sans fallback)
**Body Font:** Telegram system sans (with Noto Sans and sans-serif fallbacks)
**Label/Mono Font:** Native Telegram code formatting only when showing commands, identifiers, or measurements.

**Character:** Clear, compact, and operational. The authored banner uses a bold sans for its statement and a restrained tracked label for context. Telegram messages and buttons should use native client typography rather than trying to simulate a custom font.

### Hierarchy
- **Headline** (bold, large relative to the message): the dashboard identity and the first line of the authored banner.
- **Title** (bold): category and plugin names.
- **Body** (regular): instructions, counts, and recovery guidance.
- **Label** (semibold, tracked in authored imagery): short context labels such as workspace type or capability group.
- **Command** (native code style): command names, callback-facing identifiers, and exact configuration values.

**The Plain Label Rule.** Every button names its action in words. Emoji may be user-configured for plugin lists, but never carries the only meaning of a control.

## Layout

The primary inline dashboard opens with identity and a compact overview, then exposes categories in two columns: Plugins, Add-ons, Voice Chat, and Inline tools. Secondary actions are grouped below as System status, Settings, Support, and Close. The category list is paginated, and every detail view has a Back action. Manager help uses the same two-column grouping and adds both Add me to Group and Dashboard exits.

System status is a destination, not an update shortcut: its label reflects the Ping, Uptime, Stats, and Updates actions inside. Navigation callback data is treated as a compatibility contract and is not renamed merely to improve copy.

## Elevation & Depth

Telegram supplies the interaction surface and its own elevation model. BoudyOS does not add fake web shadows or decorative panels to messages. Depth in the authored banner comes from tonal layering, a faint grid, cyan/blue glows, and the framed logo panel; those effects stay inside the asset and never compete with message copy.

## Shapes

Controls inherit Telegram's native inline-button shape and hit area. Authored imagery uses soft 8px control-panel corners and a 16px framing radius around the logo panel. The BoudyOS mark remains square-safe with generous margins so profile and preview crops do not cut the symbol.

## Components

### Dashboard

A short BoudyOS identity block, an overview of plugin/add-on/command counts, and a single clear instruction to choose a category. It uses the branded inline asset when media is enabled and a readable article fallback when media is explicitly disabled.

### Category navigation

Two-column text buttons with stable callback data. Category labels are nouns users can scan quickly. Paging uses Previous, Back, and Next; a one-page list keeps only Back.

### Detail view

The plugin or command name is visible at the top, followed by its available commands and a compact BoudyOS source footer. The view preserves the Send plugin action when media is available and always exposes Back.

### Status surface

System status groups Ping, Uptime, Stats, and Updates under one accurately labeled destination, with Back returning to the dashboard.

### Branded media

`resources/extras/boudyos_avatar.jpg` is the canonical runtime avatar and default inline media. `resources/extras/inline.jpg` is the reproducible 16:9 preview banner generated by `scripts/build_boudyos_inline_banner.py`. Remote media is opt-in through configuration, not a random default.

## Do's and Don'ts

### Do:
- **Do** use BoudyOS in user-facing help, dashboard, assistant, status, and media copy.
- **Do** keep every operational screen reversible with Back, Close, or Dashboard.
- **Do** group actions by task and reserve the strongest visual signal for primary actions or status.
- **Do** keep exact command names and configuration values in code formatting.
- **Do** default to the immutable bundled avatar and banner; preserve explicit configured overrides.
- **Do** test callback IDs and state transitions as behavior, not only as source text.

### Don't:
- **Don't** reintroduce `@TeamUltroid`, `TeamUltroid`, or upstream support language into user-facing BoudyOS surfaces.
- **Don't** point the default inline preview at random external images or wrap local filesystem paths in web-only Telegram document types.
- **Don't** label a broad status screen as only Updates.
- **Don't** leave manager help without a Dashboard escape route.
- **Don't** use two visible On/Off controls that share a toggle callback.
- **Don't** replace readable labels with emoji-only controls or decorative glyphs.
