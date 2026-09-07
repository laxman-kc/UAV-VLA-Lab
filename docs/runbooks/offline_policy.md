# P05: recorded-observation policy probe

`scripts/offline_policy_probe.py` runs the pinned AeroVLA wrapper on three real front/down pairs from the selected demonstration trajectory. It imports no simulator environment or controller. The result is offline inference; it does not demonstrate successful flight or compare predictions to expert action labels.

Prerequisites are the verified AeroVLA checkout, converted raw dataset, the one-episode selection from `prepare_aerovla_episode.py`, and complete local OpenVLA/AeroVLA model snapshots. Use the CUDA environment established on Brev. The wrapper also imports `tkinter` even though its UI code is commented out. Run after model downloads and dataset conversion finish. Do not put observations from development or holdout into this demonstration selection.

From the lab checkout on Brev, substitute the actual upstream checkout path for `$AEROVLA_CHECKOUT`:

```sh
python scripts/offline_policy_probe.py \
  --upstream "$AEROVLA_CHECKOUT" \
  --dataset-root /home/shadeform/vla-data/assets/dataset_raw \
  --episode-selection /home/shadeform/vla-data/manifests/demo-selection-v1/selection_manifest.json \
  --base-model /home/shadeform/vla-data/assets/models/openvla-7b \
  --adapter /home/shadeform/vla-data/assets/models/AerialVLA/aero_vla \
  --output /home/shadeform/vla-data/runs/p05-offline-demo-v1
```

Every output directory must be new. Add `--validate-only` and choose a different output directory to inspect source/data/target mapping before loading the model. That mode produces `inputs_validated_model_not_run`, and does not pass P05. `--episode-selection` also accepts the generated `episode.json` rows or the locked project split manifest's single `demo` entry.

The probe checks the pinned wrapper/environment hashes and permits only the separately reviewed cancellation-propagation patch. It extracts and executes just the pure `find_closest_area` function from the verified environment source; it never imports that environment. The returned target uses the upstream selected spawn area's columns 9–11. Reports preserve the original marked target, selected spawn row and index, final benchmark target, and the original instruction verbatim. The task includes a benchmark target-position-derived bearing; it is not unknown-target navigation. A converted `merged_data.json` instruction is attributed to that file and the upstream conversion process, rather than asserted to be an independently recorded live instruction.

Selection is deterministic: first, middle, and last complete front/down/log pair, in sorted raw-log order, also present in the merged image index. Each selected log must agree exactly with both merged raw-state arrays. OpenCV reads the genuine PNGs as BGR; the pinned wrapper performs BGR-to-RGB, bicubic 224 × 224 resize, and front-above-down mosaic construction. Slots 1–3 are explicitly `None`; no left/right/rear observations are invented. The actual mosaic passed to the processor is saved.

`report.json` includes source SHA-256 hashes, rehashed local model files and matching download receipts/revisions when available, runtime packages, model dtype, per-input tensor shape/dtype/device, exact tokenizer input prompt, input/generated token IDs, decoded generation, upstream actions/stops, and a separate strict training-target grammar check. Local file hashes establish the exact bytes used; download receipts are not signatures. HF Hub/Transformers offline modes are enabled before model imports. The wrapper's fixed `./openvla-7b` location is resolved using a temporary working-directory symlink during initialization; its model-loading implementation is retained.

Generation timing uses CUDA synchronization around the actual `generate` call. Peak allocated/reserved CUDA memory includes the resident model. CPU token copying and wrapper-run duration are reported separately. There is no warmup, so the first of three samples may include lazy initialization. These three measurements are diagnostic, not a throughput benchmark. Raw data has frame indices and logged state but no validated camera-response timestamps here: report/video timing must be labeled observation sequence, not reconstructed flight time or policy rate.

`observations/` contains copied original front/down images, logged sensors, and the exact wrapper mosaic; `model_stdout.log` contains model/probe output. A partial or failed run retains `report.json` and available evidence. Exit 0 means all three generations completed and met the strict grammar; exit 2 means generation completed with an invalid case; exceptions exit nonzero. Inspect the status field because validation-only also exits 0. Strict validity is distinct from the upstream permissive parser, which can use the last three digit sequences, clamp bins, or return a zero action on malformed text. Diagnostic checks never alter its actions or stopping decisions.

For the P05 video, show the saved image pair, captioned benchmark description/prompt, actual generation and action for each selected sample. Label it **offline inference on recorded dataset observations**. Use actual report values; show invalid outputs if present. Encode after the run and attach the report, source hashes, technical video metadata, and selection rule. No navigation success, replay flight, or simulator commands are implied by this artifact.

Local implementation checks (synthetic fixtures, not acceptance evidence):

```sh
python -m unittest discover -s tests -p 'test_offline_policy.py' -v
```
