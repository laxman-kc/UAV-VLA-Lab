# MP4-only publication screen

| Phase / release | Content screen | SHA256 |
|---|---|---|
| P03 / 20260907-timedpose-v1 | candidate_mp4_only | `0132cf9aa8b648744bac1c2cba55d817bafe3c1e56434c36cd8745be142822e3` |
| P04 / 20260907-controller-rpcfix-v1 | candidate_mp4_only | `f520db1ca24dc96dde2abeaedc68e82166907d31ce0d9bad9db67159ec838a2c` |
| P04 / 20260907-timedpose-v1 | candidate_mp4_only | `3bab88b5a89b486d3822616efb443a3fccb42431e277b02297f0a351d9e25d1c` |
| P06 / 20260907-observed-v1 | candidate_mp4_only | `39e6a8993971d6dd6839bcd6ae2277d67e2e41703e90e679bc75283d1f357907` |
| P06-reference / 20260907-reference-v1 | candidate_mp4_only | `daa10868403ad8132ca6869bf72c4e4148a9e2e88a8a45afde81d345c7bb8f68` |
| P07 / 20260907-interruption-recording-v2 | candidate_mp4_only | `2b536f54bf33f3573ceb26c144d3d933258ffaf2cc20c1d8e39a215b8cfcc84f` |
| P07 / 20260907-interruption-restart-v1 | candidate_mp4_only | `b924d96f4a77f417a6a257380af6010dca638bc682582a84ac355f1969bdc5d8` |
| P10 / 20260907-reference-mechanics-logs-v1 | excluded_visible_private_or_diagnostic_content | `d78c2bda4c008d4818ce21187baa501d10a0df22b77ee23bd0ccc6850f2a25af` |
| P10 / 20260907-reference-mechanics-v1 | candidate_mp4_only | `5768943cacad5c0249ccc9c1d048cfee97596cd9e1f7b57d80d6ae59d2bf029e` |

Eight completed observation videos are candidates for separate MP4-only publication. Their visible content contains simulated scenes, benchmark/sample identifiers, action/result annotations and timing disclosures. No private host names, user paths, network addresses or hardware identifiers were found in the reviewed pixels or container metadata.

The P10 training-log video is excluded: its final stdout segment visibly includes a private output path, and its optimizer segment contains runtime memory diagnostics. Those values are intentionally not repeated here. The file requires a newly rendered public version if it is to be reconsidered.

The newer interruption/recording supplement finished artifact validation during this review. Its final hash and complete static proof were rechecked before inclusion among the eight MP4-only candidates.

Every selected rendered text field was scanned; all static slides were visually inspected. Published-reference images were inspected in the immediately preceding release review. Original slide/source hashes and completed all-frame static proofs were checked, and the actual MP4 hashes and container/stream tags were read. No audio or data streams are present. No full bundle, raw log or private provenance file accompanies these candidates.

This screen identifies a reduced review route. It does not publish, authorize publication, certify hidden-data absence or approve the private HTML reports referenced by a generic video footer.
