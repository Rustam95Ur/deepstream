# YOLO models for Nexus DeepStream

Copy (or symlink) the prepared YOLO11n tree from Campus:

```text
smart_edu/deploy/deepstream/models/yolo11n/  →  nexus_deepstream/models/yolo11n/
```

Required after prepare.sh:

- `yolo11n.onnx`
- `labels.txt`
- `nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so`

Or set `DEEPSTREAM_YOLO_DIR` to an existing prepared directory.
