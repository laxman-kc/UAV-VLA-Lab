# Recorded AeroVLA runtime family

The executable rebuild route is `uav-vla runtime bootstrap`; see the
[fresh-host runbook](../../docs/runbooks/fresh_host.md). It targets the recorded
Ubuntu 22.04 x86_64 / Python 3.10 / PyTorch 2.1.2+cu118 family. This is a GPU
environment separate from the portable standard-library package and the Mac CPU
demonstration. It is not a general `pip install [gpu]` extra or an ARM/Metal port.

`requirements-locked.txt` preserves package-version declarations from the actual
post-RPC-repair freeze and its source digest, with six separately staged packages
omitted from that file. Torch/vision/audio use the official cu118 index;
FlashAttention uses the recorded cp310/Linux wheel and SHA256. The fixed RPC ZIP
is verified against the pinned upstream checkout. AirSim's exact encoding-line
repair is preserved by `runtime repair-rpc`, with before/after source and pip logs.
Both recorded OpenCV distributions are retained; their overlapping installed
files must not be described as an additional source patch.

The recorded pins do not freeze Ubuntu apt repositories, resolver metadata,
bootstrap pip/setuptools versions, the GPU driver, or operating-system libraries.
Capture the actual freeze and fresh acceptance reports. A modern NVIDIA driver
with CUDA compatibility and working NVIDIA Vulkan/graphics support is required;
an installed CUDA Python wheel alone does not establish simulator rendering.
Bootstrap does not install, upgrade or downgrade the host GPU driver.

The previous GPU host was deleted after verified backup. This recipe has CPU
syntax/packaging/contract checks; the refactored installed workflow has not yet
been accepted on a fresh GPU host. There is no active host embedded in the package.
Run simulation and training sequentially, with one scene and one policy batch,
until a different declared configuration has been measured.
