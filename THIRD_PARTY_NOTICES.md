# Third-party notices and artifact terms

The root Apache-2.0 license applies to independently owned UAV-VLA-Lab source code and documentation. It does not relicense upstream code, model parameters, dataset content, or simulator imagery. Retain existing copyright and license notices when redistributing material.

| Component | Recorded source | Applicable information |
|---|---|---|
| AeroVLA code | [Revision e37685a](https://github.com/XuPeng23/AeroVLA/tree/e37685afb8953d1f5a09155d7255960cee1bfd9d) | [Apache-2.0](https://github.com/XuPeng23/AeroVLA/blob/e37685afb8953d1f5a09155d7255960cee1bfd9d/LICENSE). Credit its policy and integration lineage. |
| OpenVLA code and base weights | [OpenVLA](https://github.com/openvla/openvla#pretrained-vlas) | Code is MIT. The authors identify Llama-2-derived pretrained models as subject to the Llama Community License. Model-card metadata is not a replacement for inherited terms. |
| Released AerialVLA adapter | [Pinned model card](https://huggingface.co/XuPeng23/AerialVLA/blob/196f2f3253b69df6e90ac10b6ae041c7b3a9569e/README.md) | Card declares Apache-2.0; base-model lineage must also be considered. Download stock artifacts from their official publisher. |
| TravelUAV code, data, environments | [Pinned source](https://github.com/prince687028/TravelUAV/tree/5cc26e9a4a55b9c788e918f7c3bb2dc5076a85e6) | The inspected root lacks a repository-wide license. Nested LLaMA-UAV code has Apache terms; its nested DATA_LICENSE and WEIGHT_LICENSE are CC-BY-NC-4.0. Scope over separate raw/environment/annotation downloads is not explicit. |
| AirSim and transport dependencies | [AirSim](https://github.com/microsoft/AirSim), recorded runtime requirements | Keep the respective distribution licenses and recorded transport-repair attribution. |
| Rendered simulator footage | TravelUAV environments and their content sources | Research clips are derived media, not a grant to redistribute environment binaries or raw datasets. Upstream pixels do not inherit the root code license. |

The public artifact catalog records availability and source identities. The final adapter's recipe, numeric results, lineage and hashes can be inspected independently of binary availability. Binary redistribution remains pending documentation of applicable upstream model and dataset terms; the code release does not represent that review as complete.

Research organization references include [LeRobot](https://github.com/huggingface/lerobot), [OpenVLA](https://github.com/openvla/openvla), [openpi](https://github.com/Physical-Intelligence/openpi), [robomimic](https://github.com/ARISE-Initiative/robomimic), and [Diffusion Policy](https://github.com/real-stanford/diffusion_policy). Their organization informed the package, example and artifact presentation. They are not claimed as implemented policy backends.
