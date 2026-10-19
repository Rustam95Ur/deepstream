# Models for Nexus DeepStream

No Ultralytics / AGPL code or weights. Two models, downloaded on the first start of
the video container (`shell/video-boot.sh` runs each `prepare.sh` when its file is
missing; files stay on the host through the `./models` volume):

| Dir | Model | Role | Licence |
|---|---|---|---|
| `peoplenet/` | NVIDIA TAO PeopleNet v2.6.3 (ResNet34, ONNX) | people boxes (PGIE), classes person/bag/face | NVIDIA TAO model licence — see the NGC model card |
| `rtmpose/` | RTMPose-m (OpenMMLab), 17 COCO keypoints | skeleton per tracked person (SGIE) | Apache-2.0 |

Tracking: NvDCF from the DeepStream image (`DEEPSTREAM_TRACKER_CONFIG`,
`DEEPSTREAM_TRACKER_LIB`).

## Prepare by hand

```bash
docker compose exec pipeline bash /opt/nexus_deepstream/models/peoplenet/prepare.sh
docker compose exec pipeline bash /opt/nexus_deepstream/models/rtmpose/prepare.sh
```

- `peoplenet/`: `resnet34_peoplenet.onnx`, `labels.txt` (+ INT8 calibration file).
  DeepStream's built-in DetectNet_v2 parser, nothing to compile. Override the
  version with `PEOPLENET_VERSION`.
- `rtmpose/`: downloads the ONNX and runs `add_decode.py`, which appends the SimCC
  decode so the model outputs `keypoints` (N x 17 x 3) directly →
  `rtmpose_kpts.onnx`. Override the source with `RTMPOSE_ZIP_URL` or a local
  `RTMPOSE_ONNX`.

**Training-data note:** the default RTMPose checkpoint is trained on "body7" (COCO +
six other public pose datasets, some with research-only terms). If that matters
for a deployment, point `RTMPOSE_ONNX` at a COCO-only export — same inputs and
outputs, no code change.

If `rtmpose_kpts.onnx` is missing the pipeline still runs; the `vif` trigger then
works on box contact alone (logged as a warning).
