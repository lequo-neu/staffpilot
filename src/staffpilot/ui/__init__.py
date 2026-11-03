"""Look and building blocks of the web app ("Ledger" design).

* `theme.py`: the Gradio theme and the stylesheet (`style.css`),
* `components.py`: small HTML pieces (brand, stat strip, alerts, page headers),
  shared by every page so the pages stay consistent.

The handlers and the layout live in `staffpilot.app`.
"""

from staffpilot.ui.theme import CSS, theme


__all__ = ["CSS", "theme"]
