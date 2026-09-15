/**
 * Demo scope gate — the UI half of app/main.py DEMO_FEATURES.
 *
 * The demo is cut to one value chain: predict flood -> update road state -> recommend
 * route. Panels off that chain are hidden here rather than deleted, so the components
 * stay in the tree and a flag flip brings them back.
 *
 * Deliberately a hardcoded mirror rather than a fetch of /v1/features: the panel gate
 * has to be settled before first paint, and a boot-time round-trip to learn which
 * buttons to draw would trade a flicker for no real benefit. The backend stays the
 * authority — it 404s a disabled route whatever this file says.
 */
export const FEATURES = {
  // spine
  routing: true,
  inspector: true,
  weather: true,
  assistant: true,
  timeSlider: true,
  observations: true,
  opsClosure: true,
  sensorCoverage: true,   // overlay toggle, not a panel — the coverage-gap argument

  // off-scope, components retained
  charging: false,
  environment: false,
} as const;
