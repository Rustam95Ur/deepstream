# YOLO models for Nexus DeepStream

GPU pipeline needs a prepared YOLO11n tree at `models/yolo11n` (or `DEEPSTREAM_YOLO_DIR`):

- `yolo11n.onnx`
- `labels.txt`
- `nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so`

## Prepare (recommended)

Inside the DeepStream container (needs GPU image, internet, first run several minutes):

```bash
docker compose exec nexus-deepstream-video bash /opt/nexus_deepstream/models/yolo11n/prepare.sh
```

`shell/video-boot.sh` runs the same script on **first** video-container start when ONNX / parser `.so` are missing. Generated files stay on the host via the `./models` volume.

## Copy from Campus

```text
smart_edu/deploy/deepstream/models/yolo11n/  →  nexus_deepstream/models/yolo11n/
```
