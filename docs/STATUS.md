# Implementation status

Updated 7 September 2026 UTC. This file records observed progress, not completion promises.

The user authorized GitHub publication and execution on Brev `vla01` through all planned phases. The repository is `laxman-kc/UAV-VLA-Lab`; the first planning commit was pushed to `main`.

| Area | Observed status |
|---|---|
| Brev connection | Working |
| Actual VM | Ubuntu 22.04.5, 14 exposed CPUs, 74,195,796 KiB system RAM |
| Allocation discrepancy | User listing says 26 CPUs/192 GB; execution uses measured 14 CPUs/about 70.76 GiB |
| GPU | NVIDIA L40, 46,068 MiB exposed VRAM, driver 580.126.09 |
| Graphics | Vulkan enumerates the actual NVIDIA L40 |
| Initial available storage | 612,665,286,656 bytes on the mounted ext4 root filesystem |
| Runtime imports | All 15 checked modules passed |
| GPU operation | BF16 CUDA matrix multiplication passed using PyTorch 2.1.2/cu118 |
| Dependencies | OpenCV/NumPy conflict resolved; pip check passed; exact environment freeze recorded |
| Assets | Pinned ModernCityMap and released model downloads in progress |
| P01 artifacts | Report/video packaging in progress |
| P02–P14 | Not yet completed |

The data root is `/home/shadeform/vla-data`. A mounted filesystem was verified; stop/resume persistence was not tested by stopping this active VM. Raw observations, checkpoints and videos stay outside source Git.

The initial task uses the official target-bearing-assisted inputs. The correction-source choice remains pending; it does not block simulator/model integration. No closed-loop success, training improvement, or completed phase video is claimed yet.
