# P01 — Brev host readiness

Executed 7 September 2026 UTC on the recorded experiment allocation. Engineering gate: **passed with explicit limits**. Navigation and training were not exercised by this phase.

This public summary omits the original instance label and filesystem path. The retained execution report and sealed evidence are unchanged.

| Measurement | Observed value |
|---|---|
| Operating system | Ubuntu 22.04.5 LTS, x86_64 |
| Exposed CPUs | 14 |
| System RAM | 74,195,796 KiB, approximately 70.76 GiB |
| GPU | NVIDIA L40, 46,068 MiB exposed VRAM |
| NVIDIA driver | 580.126.09 |
| Initial free storage | 612,665,286,656 bytes |
| Data root | `<recorded-data-root>` on the observed ext4 root mount; original path omitted from this public summary |
| Runtime | Python 3.10; PyTorch 2.1.2 with CUDA 11.8 |
| Import checks | All 15 checked modules passed |
| CUDA operation | Actual BF16 matrix operation passed |
| Dependency consistency | `pip check` passed after documented OpenCV/NumPy repairs |
| Graphics prerequisite | Vulkan enumerated the NVIDIA L40 |

The exposed CPU and memory allocation differs from the user-provided Brev listing of 26 CPUs and 192 GB. Capacity planning uses the measured allocation. A stop/resume cycle was not performed, so persistence through that operation remains unverified. Vulkan enumeration is a prerequisite check; actual Unreal rendering belongs to P03.

The release contains both host snapshots, exact commands, runtime logs, dependency freeze, checks, report, runbook and checksums. Its 98-second H.264 video displays actual recorded diagnostic excerpts with assigned hold durations. It is not a live terminal recording. Every static segment was visually inspected; all 980 encoded frames and their timestamps were technically checked against those reviewed references. The review does not claim continuous playback was watched.

P01 is a dated snapshot. Later FlashAttention/native CUDA changes and offline model execution are recorded separately in P05, without rewriting the earlier evidence.

Release identifier: `20260907-readiness-v1`. Source implementation: `scripts/host_probe.py`, `scripts/runtime_probe.py`, `scripts/bootstrap_brev.sh`, and `scripts/build_release.py`. The full bundle is retained outside this source distribution. Published media are listed in the [video record](../research/videos.md).
