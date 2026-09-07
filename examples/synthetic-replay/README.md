# Synthetic CPU replay

This hand-authored mathematical point example needs Python 3.10+ and the core package. It contains no model, camera data, collision physics, physical timing or navigation outcome.

From an installed package, in any working directory:

```sh
uav-vla doctor
uav-vla demo --output runs/synthetic-demo
uav-vla verify runs/synthetic-demo
```

Open `runs/synthetic-demo/report.html` to inspect the XY trace, four logical actions, five states and links to their source. The example is bundled in the wheel; no repository checkout or download is needed after installation. Every output directory must be new.

To change the hand-authored input, copy `input.json` from this example and run:

```sh
uav-vla replay input.json --output runs/my-synthetic-replay
```

Inputs use `vla.synthetic-replay.v1`. Coordinates are local NED metres and yaw is in radians. Each action first adds its yaw delta, then translates along the new body-forward direction and the down axis. A logical action index has no physical duration. These are example semantics, not the AeroVLA controller contract.

For the bundled input, the final position is approximately `(1, 1.5, -0.25)` and yaw is zero. The mathematical path length is approximately `2.559017` metres. Navigation success and physical elapsed seconds remain null.

The output includes exact input bytes, resolved configuration, causal events, metrics, SVG, HTML, Markdown and a SHA256 inventory. Verification checks the inventory, requires the recorded core source hashes to match the installed implementation, and recomputes the expected replay, metrics and reports. Keep that implementation when archiving a replay. Changing an event and updating its hash still fails semantic verification. A manifest can be replaced, so this checks internal consistency and file integrity, not authorship or signed provenance.

This fixture is deliberately synthetic and may be redistributed with the project source. It does not grant rights to upstream images, models or simulator assets.
