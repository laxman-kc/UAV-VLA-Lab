# ModernCityMap asset runbook

Installed package entrypoints and the distinction between native modules and historical compatibility engines are documented in [installed workflows](installed_workflows.md). New GPU hosts follow [fresh-host acceptance](fresh_host.md); the completed-cycle host was retired.


The selected map is **ModernCityMap**, the smallest complete published raw-map plus environment archive groups among the maps in the released AeroVLA evaluation files and executable mapping. This is a download-size decision, not a claim that its missions are easiest. The exact filenames, immutable URLs, byte sizes and SHA256 values are in [`configs/assets/modern_city_map.json`](../../configs/assets/modern_city_map.json).

## Verified inventory

| Item | Files | Download bytes |
|---|---|---:|
| Raw map | `ModernCityMap.z01`, `.z02`, `.zip` | 9,847,057,165 |
| Shared environment bundle | `closeloop_envs.z01` through `.z04`, plus `.zip` | 18,645,702,495 |
| Total | Eight archive parts | **28,492,759,660** |

All parts of each split ZIP are required for the normal extraction workflow. The raw repository revision is `faa8f2514156455ea7423464cc1295e6f92575cb`; the environment revision is `44de5739a95a2f6a88767446421cddada9606642`. Keep filenames unchanged and each bundle's parts together. Model weights are a separate acquisition.

Bounded ZIP central-directory inspection found 718 raw trajectories and the selected demo's required metadata paths. The archives declare 10,159,691,009 raw expanded bytes and 19,576,208,267 expanded environment bytes. Archives plus full extraction therefore declare 58,228,658,936 bytes. Budget additional filesystem overhead, temporary joined archives, models, caches and run outputs; measure actual free space before acquisition. Byte declarations and file listings do not prove payload integrity or runtime compatibility.

The environment launcher is `envs/closeloop_envs/ModernCityMap.sh`. Its binary directory is named **ModernCityDowntown**: `envs/closeloop_envs/ModernCityDowntown/Binaries/Linux/ModernCityDowntown`. Preserve the shared `closeloop_envs/Engine` files. Do not rename the binary directory to the map ID.

## Episode partition

[`configs/splits/modern_city_map_v1.json`](../../configs/splits/modern_city_map_v1.json) freezes:

| Purpose | Unique episodes |
|---|---:|
| Official TravelUAV training membership | 594 |
| Demo | 1 |
| Development | 20 |
| Adaptation holdout | 10 |
| Unassigned seen episodes | 93 |

The demo is `ModernCityMap/23cda8d5-d239-4b15-bcf8-ffdb28a43f07/merged_data.json`. It was chosen by the minimum evaluation-row count, then path order; this does not establish the shortest physical route. All 124 released seen episodes are disjoint from the 594 official training episodes. The remaining partition uses the exact SHA256 ordering rule recorded in the split manifest.

The training source is `TravelUAV_data_json` revision `5a1ed4c99d3e7bb2b35fa34135910cb7687fc831`, `data/uav_dataset/trainset.json`. The AeroVLA evaluation source is pinned at `e37685afb8953d1f5a09155d7255960cee1bfd9d`.

This is a **same-map adaptation holdout**. The released AeroVLA cleaned training JSON has not been audited for overlap, and no claim is made that these episodes were absent from the original model's training. ModernCityMap has no released unseen-object or unseen-map evaluation file. Do not inspect holdout camera contents or use holdout labels/results to select corrections or checkpoints.

## Preparation and archive verification

Run these commands from the project checkout in the selected Python environment. The remote data root was selected as `/actual/persistent/vla-data`; the archive staging directory below is a configurable convention, not evidence of completed downloads.

```bash
export VLA_DATA_ROOT=/actual/persistent/vla-data
export VLA_ARCHIVE_DIR="$VLA_DATA_ROOT/assets/archives"
python scripts/prepare_assets.py plan
```

Download the manifest's eight assets with the experiment runner's resumable downloader. Do not clone the full Hugging Face dataset. The asset utility does not download archives or install extraction tools. After the downloader finishes:

```bash
python scripts/prepare_assets.py \
  --report "$VLA_DATA_ROOT/manifests/asset-checks/archives.json" \
  verify --archive-dir "$VLA_ARCHIVE_DIR/dataset_raw" --category dataset_raw
python scripts/prepare_assets.py \
  --report "$VLA_DATA_ROOT/manifests/asset-checks/env-archives.json" \
  verify --archive-dir "$VLA_ARCHIVE_DIR/envs" --category envs
```

A missing file, incorrect length or SHA256 mismatch fails the gate. Partial downloads do not count as complete files. Keep failed files for diagnosis; do not overwrite a verified archive with a new unpinned version.

## Extraction

First establish which split-ZIP extractor is installed and supported. With a verified `7z` or `7zz` installation, list/test the archive before extracting. Commands below use `7z` as the verified executable name; substitute `7zz` if that is the installed tool.

```bash
7z l "$VLA_ARCHIVE_DIR/dataset_raw/ModernCityMap.zip"
7z l "$VLA_ARCHIVE_DIR/envs/closeloop_envs.zip"
7z t "$VLA_ARCHIVE_DIR/dataset_raw/ModernCityMap.zip"
7z t "$VLA_ARCHIVE_DIR/envs/closeloop_envs.zip"
mkdir -p "$VLA_DATA_ROOT/assets/dataset_raw" "$VLA_DATA_ROOT/assets/envs"
7z x "$VLA_ARCHIVE_DIR/dataset_raw/ModernCityMap.zip" \
  "-o$VLA_DATA_ROOT/assets/dataset_raw"
7z x "$VLA_ARCHIVE_DIR/envs/closeloop_envs.zip" \
  "-o$VLA_DATA_ROOT/assets/envs"
```

Do not continue on an unsupported multi-volume error. If the installed extractor cannot read these split ZIPs, use a verified Info-ZIP `zip -s 0 input.zip --out joined.zip` conversion, then test/extract the joined ZIP. Reserve space for the joined copies and record the commands. This fallback is documented, not claimed to have been run on Brev.

The archive already includes its top-level map/bundle directories. Check for accidental double nesting. Restore executable permission only on the selected verified launcher/binary if extraction did not preserve it:

```bash
chmod u+x "$VLA_DATA_ROOT/assets/envs/closeloop_envs/ModernCityMap.sh"
chmod u+x "$VLA_DATA_ROOT/assets/envs/closeloop_envs/ModernCityDowntown/Binaries/Linux/ModernCityDowntown"
python scripts/prepare_assets.py \
  --report "$VLA_DATA_ROOT/manifests/asset-checks/extracted-demo.json" \
  validate --data-root "$VLA_DATA_ROOT" --groups demo
```

The validator checks metadata shapes, finite poses, log references, paired front/down PNG headers and binary executable permission. It does not launch the simulator or fully decode images; those remain the observation smoke-test gate.

## Generate `merged_data.json`

The correct upstream converter path is **`Model/LLaMA-UAV/tools/generate_merged_json.py`**, not `tools/generate_merged_json.py` from the repository root. Use TravelUAV revision `5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6`; the exact source URL and hash are in the asset manifest. Store that small pinned source file under a declared tools directory, verify it, then run:

```bash
python scripts/prepare_assets.py convert \
  --data-root "$VLA_DATA_ROOT" \
  --converter /absolute/path/to/pinned/generate_merged_json.py \
  --seed 100
python scripts/prepare_assets.py \
  --report "$VLA_DATA_ROOT/manifests/asset-checks/converted-demo.json" \
  validate --data-root "$VLA_DATA_ROOT" --groups demo --require-merged
```

The helper refuses a converter hash mismatch. It seeds Python's random generator before executing unchanged upstream source because upstream assigns `random.seed = 1` instead of calling it. Record the seed and wrapper version. Upstream traversal and skip-existing behavior remain unchanged, so **do not claim regeneration is byte-identical across filesystems or partial resumes**. Preserve and hash the generated metadata as part of the dataset revision. Generating a fresh deterministic per-episode metadata revision would be a separate documented converter change.

The underlying converter needs logs, `object_description.json`, and matching `frontcamera` files; fewer than five matched front frames are skipped. It writes trajectory metadata and an instruction. Training additionally needs the `downcamera` files. This utility does **not** generate the cleaned AeroVLA action-label training JSON or certify its temporal label horizon.

Validate development/training groups separately when their phase needs them. Metadata-only reference checks may be performed for a quarantined holdout without showing its images or target descriptions. The helper never prints those contents.

## Completion record

Save the pinned asset and split manifests, archive checks, extraction commands/tool version, free-space measurements, converter source hash/seed, generated metadata hashes, and selected-demo validation report. A passing asset gate establishes file integrity and required references. Simulator execution, policy compatibility and navigation outcomes have separate gates.

## Primary sources

- [TravelUAV raw archives](https://huggingface.co/datasets/wangxiangyu0814/TravelUAV/tree/faa8f2514156455ea7423464cc1295e6f92575cb)
- [TravelUAV compiled environment archives](https://huggingface.co/datasets/wangxiangyu0814/TravelUAV_env/tree/44de5739a95a2f6a88767446421cddada9606642)
- [Official training split metadata](https://huggingface.co/datasets/wangxiangyu0814/TravelUAV_data_json/tree/5a1ed4c99d3e7bb2b35fa34135910cb7687fc831/data/uav_dataset)
- [Pinned TravelUAV metadata converter](https://github.com/prince687028/TravelUAV/blob/5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6/Model/LLaMA-UAV/tools/generate_merged_json.py)
- [Pinned AeroVLA map split](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/data/uav_dataset/seen_valset_splits/ModernCityMap.json)
