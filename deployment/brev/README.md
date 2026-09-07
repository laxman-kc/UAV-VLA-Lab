# Brev deployment boundary

Brev is an optional provider for the [fresh-host recipe](../../docs/runbooks/fresh_host.md).
No account, instance ID, hostname, SSH alias or provider credential is part of the
portable runtime. The previous completed-cycle host was deleted after backup;
historical capacity and paths do not select a replacement.

Select a Linux x86_64 NVIDIA graphics-capable instance explicitly, then verify
the delivered OS, CPU/RAM, available disk, CUDA operation and NVIDIA Vulkan device.
A provider's advertised capacity is distinct from the delivered inventory.
Choose a persistent data mount and establish its lifecycle before relying on it.
The bootstrap requires Ubuntu 22.04 and Python 3.10; other images need a separately
reviewed recipe. Rootless containers would additionally require explicit NVIDIA
compute and graphics device/library passthrough; a container recipe is not claimed.

Develop/build the wheel on the Mac, transfer that wheel and the declared small
manifests, and run bootstrap through SSH on the selected host. Use a terminal
multiplexer for the operator session and `uav-vla simulate` for owned workload
lifecycle/evidence. Keep scene/RPC ports private to the host; the evaluator and
manager share that host. No public inbound simulator port is required. SSH itself
does not turn the Mac into the simulator/GPU runtime.

Provisioning, billing limits, stop/delete and remote artifact transfer are
operator actions. This package does not provision or delete a host. Before any
deletion, copy unique checkpoints/source/config/complete attempt evidence and
verify the copies. Released stock assets can be acquired again from the pinned
intent, whereas new experiment outputs need their own backups.
