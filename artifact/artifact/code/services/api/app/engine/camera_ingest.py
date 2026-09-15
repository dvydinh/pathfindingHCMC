"""Interface stub: traffic-camera flood classification -> engine observation record.

STATUS: STUB. There is no model behind this file and no camera data in the project.
It contains no inference, no image handling, and no machine-learning dependency — only
the type definitions and the mapping that a future classifier would have to satisfy.
It is deliberately not mounted in ``app.main`` and is not a feature flag; importing it
has no effect on a running service. See ``docs/CAMERA_FEASIBILITY.md`` for the
assessment this file accompanies.

Why the stub exists at all: the assimilation layer in :mod:`app.engine.state` already
accepts noisy observations from named feeds, and the point of the feasibility study is
that a camera classifier would need **no new format** — it reuses the record shape that
citizen reports already use (``app/routers/observations.py:53-56``). Writing that shape
down as code is the cheapest way to keep the claim honest and checkable.

The record contract, as consumed by ``Scenario._log_lik`` (``state.py:88-99``):

    {
        "feed_id":      str,          # stable per camera; namespaces the source
        "source_class": "camera",     # surfaced by Scenario.source_mix()
        "edge":         int,          # ARRAY INDEX into Graph, not the edge_id string
        "tick":         int,          # scenario tick the observation belongs to
        "interval_cm":  [lo, hi],     # depth bracket in centimetres
    }

Two likelihood forms exist and only these two. A record carrying ``depth_cm`` is scored
as a Gaussian with ``noise_cm`` as sigma; anything else is scored as a soft interval on
``interval_cm``. A camera cannot produce a calibrated point depth, so the interval form
is the correct one and the only one used here.

There is no per-observation weight or confidence field in the schema. Classifier
confidence is therefore expressed the only way the engine can read it: by widening the
reported interval. A wide bracket overlaps more ensemble members, so its log-likelihood
discriminates between them less, and the posterior stays closer to the physics prior.
That is the same mechanism that makes a vague citizen report count for little, and it is
what makes the night/rain/offline failure modes degrade gracefully rather than mislead.
"""
from __future__ import annotations

from enum import Enum

# Confidence below this is treated as no observation at all. A classifier that is
# unsure should stay silent rather than nudge the posterior with noise: the engine has a
# physics prior that is better than a coin flip.
MIN_CONFIDENCE = 0.35

# Widening applied at zero confidence, in centimetres added to each side of the
# bracket. At confidence 1.0 the base bracket is used unchanged.
UNCERTAINTY_SPREAD_CM = 12.0

# Upper bound used for the open-ended flooded bracket. Matches the top of
# CATEGORY_CM in app/routers/observations.py so both sources share a scale.
MAX_DEPTH_CM = 120.0


class FloodClass(str, Enum):
    """Ordinal flood state a low-resolution traffic camera can plausibly support.

    Deliberately three states plus an abstention. Centimetre-level depth regression from
    these cameras is not achievable — there is no reference scale in frame, the mounting
    geometry is unknown and uncalibrated, and night and rain destroy the signal. An
    ordinal call is the strongest claim the imagery supports.

    Attributes:
        DRY: No standing water visible on the carriageway.
        WET: Surface water visible but road markings and kerb line still readable;
            passable for every vehicle class in the envelope table.
        FLOODED: Standing water obscuring road markings or reaching kerb height.
            A camera cannot separate 20 cm from 60 cm, so this class maps to a
            deliberately wide bracket rather than a depth.
        UNKNOWN: Abstention. Night without lighting, lens occluded by rain, stream
            offline, or classifier confidence below threshold. Produces no observation.
    """

    DRY = "dry"
    WET = "wet"
    FLOODED = "flooded"
    UNKNOWN = "unknown"


# Base depth bracket per class, in centimetres. Aligned with CATEGORY_CM in
# app/routers/observations.py so a camera call and a citizen report on the same edge
# are on one scale and can be compared rather than silently double-counted.
CLASS_INTERVAL_CM: dict[FloodClass, tuple[float, float]] = {
    FloodClass.DRY: (0.0, 3.0),
    FloodClass.WET: (3.0, 15.0),
    FloodClass.FLOODED: (15.0, MAX_DEPTH_CM),
}


def interval_for(flood_class: FloodClass, confidence: float) -> tuple[float, float] | None:
    """Widen a class bracket according to classifier confidence.

    Args:
        flood_class: Ordinal call from the classifier.
        confidence: Classifier confidence in [0, 1].

    Returns:
        The ``(lo_cm, hi_cm)`` bracket to report, widened by
        ``(1 - confidence) * UNCERTAINTY_SPREAD_CM`` on each side and clamped to
        ``[0, MAX_DEPTH_CM]``. Returns ``None`` for :attr:`FloodClass.UNKNOWN` or for
        confidence below :data:`MIN_CONFIDENCE`, meaning no observation should be
        emitted.
    """
    if flood_class is FloodClass.UNKNOWN or confidence < MIN_CONFIDENCE:
        return None
    lo, hi = CLASS_INTERVAL_CM[flood_class]
    pad = (1.0 - max(0.0, min(1.0, confidence))) * UNCERTAINTY_SPREAD_CM
    return (max(0.0, lo - pad), min(MAX_DEPTH_CM, hi + pad))


def to_observation(camera_id: str, edge: int, tick: int, flood_class: FloodClass,
                   confidence: float) -> dict | None:
    """Map one classifier call to the observation record the engine already accepts.

    The returned dict is appended to ``Scenario.user_obs`` by a caller, which must then
    call ``Scenario.bump()`` to invalidate the posterior caches — exactly the sequence
    ``app/routers/observations.py:52-57`` performs for a citizen report. This function
    does not touch the scenario; it is a pure mapping so it can be unit-tested without a
    loaded scene.

    Args:
        camera_id: Stable identifier for the camera, e.g. its agency station code.
            Becomes ``feed_id``, which namespaces the source and is what an outage
            switch would key on.
        edge: Array index of the edge the camera overlooks — ``Graph.idx[edge_id]``,
            not the ``edge_id`` string. Establishing this mapping is a manual siting
            task per camera and is the main integration cost of the whole feature.
        tick: Scenario tick the observation belongs to. Mapping wall-clock time to a
            tick is unresolved for live data; see the interface-gaps section of
            ``docs/CAMERA_FEASIBILITY.md``.
        flood_class: Ordinal call from the classifier.
        confidence: Classifier confidence in [0, 1].

    Returns:
        An observation record, or ``None`` when the call carries no usable information
        (abstention or low confidence). A ``None`` return is the normal, expected
        outcome at night and in heavy rain; the caller should drop it and let the
        physics prior stand rather than substituting a default.

    Example:
        >>> to_observation("CAM-042", 1234, 22, FloodClass.FLOODED, 0.9)
        {'feed_id': 'CAM-042', 'source_class': 'camera', 'edge': 1234, 'tick': 22, \
'interval_cm': [13.8, 120.0]}
    """
    interval = interval_for(flood_class, confidence)
    if interval is None:
        return None
    return {
        "feed_id": camera_id,
        "source_class": "camera",
        "edge": int(edge),
        "tick": int(tick),
        "interval_cm": [round(interval[0], 1), round(interval[1], 1)],
    }
