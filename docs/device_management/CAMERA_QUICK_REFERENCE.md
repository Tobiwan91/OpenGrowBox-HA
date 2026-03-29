# Camera System - Quick Reference

## File Locations

### Source Images

| Type             | Path                                              |
|------------------|---------------------------------------------------|
| Daily Snapshots  | `/config/ogb_data/{room}_img/{camera}/daily/`     |
| Timelapse Images | `/config/ogb_data/{room}_img/{camera}/timelapse/` |

### Output Files

| Type             | Path                                                | Access URL                                               |
|------------------|-----------------------------------------------------|----------------------------------------------------------|
| Timelapse Videos | `/config/www/ogb_data/{room}_img/timelapse_output/` | `/local/ogb_data/{room}_img/timelapse_output/{filename}` |
| Daily ZIPs       | `/config/www/ogb_data/{room}_img/daily_output/`     | `/local/ogb_data/{room}_img/daily_output/{filename}`     |

### State Files

| Type           | Path                                     |
|----------------|------------------------------------------|
| Room State     | `/config/ogb_data/ogb_{room}_state.json` |
| PlantsView Key | `plantsView` within room state           |

---

## File Naming

| Type            | Format                                       | Example                                            |
|-----------------|----------------------------------------------|----------------------------------------------------|
| Daily Snapshot  | `YYYY-MM-DD_HHMMSS.jpg`                      | `2026-03-29_090000.jpg`                            |
| Timelapse Image | `{device}_YYYYMMDD_HHMMSS.jpg`               | `camera1_20260329_120000.jpg`                      |
| Timelapse Video | `timelapse_{device}_{plant}_{timestamp}.mp4` | `timelapse_camera1_blue_dream_20260329_120000.mp4` |
| Timelapse ZIP   | `timelapse_{device}_{plant}_{timestamp}.zip` | `timelapse_camera1_blue_dream_20260329_120000.zip` |

---

## Events Reference

### Frontend → Backend Events

| Event | Purpose | Key Parameters |
|-------|---------|----------------|
| `opengrowbox_get_timelapse_config` | Request config | `device_name` |
| `opengrowbox_save_timelapse_config` | Save config | `device_name`, `config` |
| `opengrowbox_start_timelapse` | Start recording | `device_name` |
| `opengrowbox_stop_timelapse` | Stop recording | `device_name` |
| `opengrowbox_generate_timelapse` | Generate video | `device_name`, `start_date`, `end_date`, `format` |
| `opengrowbox_get_timelapse_status` | Get status | `device_name` |
| `opengrowbox_get_daily_photos` | List photos | `device_name` |
| `opengrowbox_get_daily_photo` | Get single photo | `device_name`, `date` |
| `opengrowbox_delete_daily_photo` | Delete photo | `device_name`, `date` |
| `opengrowbox_delete_all_daily` | Delete all daily | `device_name` |
| `opengrowbox_download_daily_zip` | Create ZIP | `device_name`, `start_date`, `end_date` |
| `opengrowbox_delete_all_timelapse` | Delete timelapse images | `device_name` |
| `opengrowbox_delete_all_timelapse_output` | Delete videos | `device_name` |
| `opengrowbox_get_timelapse_photos` | List timelapse | `device_name` |

### Backend → Frontend Events

| Event | Purpose | Key Fields |
|-------|---------|------------|
| `TimelapseConfigResponse` | Config data | `current_config`, `tl_active`, `tl_image_count` |
| `TimelapseConfigSaved` | Save confirm | `config` |
| `CameraRecordingStatus` | Status update | `is_recording`, `image_count`, `is_night_mode` |
| `TimelapseCompleted` | Recording done | `total_images`, `duration` |
| `TimelapseGenerationStarted` | Gen started | `format` |
| `TimelapseGenerationProgress` | Gen progress | `progress` (0-100), `status` |
| `TimelapseGenerationComplete` | Gen done | `success`, `download_url`, `error` |
| `DailyPhotosResponse` | Photo list | `photos`, `count` |
| `DailyPhotoResponse` | Single photo | `image_data`, `date` |
| `DailyZipResponse` | ZIP ready | `download_url`, `photo_count` |
| `ogb_camera_capture_failed` | Capture error | `error`, `retry_count` |
| `ogb_camera_daily_photo_captured` | Daily success | `date`, `filename` |
| `ogb_camera_photo_deleted` | Delete confirm | `date` |
| `ogb_camera_all_daily_deleted` | Bulk delete | `deleted_count` |

---

## Configuration Options

### PlantsView Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `isTimeLapseActive` | boolean | false | Recording active |
| `TimeLapseIntervall` | string | "900" | Capture interval (seconds) |
| `StartDate` | string | "" | ISO datetime when to start |
| `EndDate` | string | "" | ISO datetime when to stop |
| `OutPutFormat` | string | "mp4" | Output format: "mp4" or "zip" |
| `tl_image_count` | number | 0 | Images captured this session |
| `daily_snapshot_enabled` | boolean | false | Daily snapshots active |
| `daily_snapshot_time` | string | "09:00" | Time for daily capture |
| `capture_at_night` | boolean | false | Capture during lights off |

---

## Capture Intervals

| Interval | Images/Day | Storage/Day | Best For |
|----------|------------|-------------|----------|
| 5 min (300s) | 288 | ~150 MB | Detailed monitoring |
| 10 min (600s) | 144 | ~75 MB | Balanced recording |
| 15 min (900s) | 96 | ~50 MB | Standard timelapse |
| 30 min (1800s) | 48 | ~25 MB | Long-term tracking |
| 1 hour (3600s) | 24 | ~12 MB | Minimal monitoring |

---

## Generation Status Values

| Status | Meaning |
|--------|---------|
| `idle` | No generation active |
| `scanning` | Finding images |
| `preparing` | Setting up |
| `creating_zip` | Building ZIP archive |
| `encoding_video` | FFmpeg processing |
| `complete` | Successfully finished |
| `error` | Generation failed |

---

## HTTP Endpoints

### Camera Proxy

```
GET /api/camera_proxy/{entity_id}
Authorization: Bearer {token}
Response: image/jpeg
```

### Camera Stream

```
WebSocket message:
{
  "type": "camera/stream",
  "entity_id": "camera.grow_room"
}

Response:
{
  "url": "http://homeassistant:8123/api/camera_proxy_stream/..."
}
```

### Output File Download

```
GET /local/ogb_data/{room}_img/timelapse_output/{filename}
GET /local/ogb_data/{room}_img/daily_output/{filename}
```

---

## Troubleshooting Checklist

### Live Streaming Issues

- [ ] Camera entity exists in HA
- [ ] Camera assigned to correct room
- [ ] HA token valid (try re-login)
- [ ] Check browser console for errors
- [ ] Falls back to still images automatically

### Daily Snapshot Issues

- [ ] `daily_snapshot_enabled` is true
- [ ] Time format is "HH:MM"
- [ ] Camera accessible at scheduled time
- [ ] Storage directory exists and is writable
- [ ] Check HA logs for capture errors

### Timelapse Recording Issues

- [ ] `StartDate` before `EndDate`
- [ ] Interval at least 30 seconds
- [ ] Lights ON or `capture_at_night` enabled
- [ ] Storage has free space
- [ ] Check `CameraRecordingStatus` events

### Video Generation Issues

- [ ] FFmpeg installed (`ffmpeg -version`)
- [ ] At least 10 images captured
- [ ] Sufficient disk space for output
- [ ] Check `TimelapseGenerationComplete` for errors
- [ ] Try ZIP format as alternative

---

## Module Quick Reference

| Module | File | Purpose |
|--------|------|---------|
| Camera | `__init__.py` | Coordinator, lifecycle |
| Capture | `capture.py` | Image capture, retry logic |
| Scheduler | `scheduling.py` | Timelapse & daily timers |
| Storage | `storage.py` | File I/O, path validation |
| VideoGenerator | `video_generator.py` | FFmpeg video creation |
| Handlers | `handlers.py` | HA event routing |
| Utils | `utils.py` | Pure utility functions |

---

## Debug Logging

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.opengrowbox.OGBController.OGBDevices.Camera: debug
```

---

## Related Documentation

| Document | Audience | Content |
|----------|----------|---------|
| [CAMERA_ARCHITECTURE.md](../specialized_systems/CAMERA_ARCHITECTURE.md) | Architects | System design, patterns |
| [CAMERA_USER_GUIDE.md](CAMERA_USER_GUIDE.md) | Users | Features, usage |
| [CAMERA_DEVELOPER_GUIDE.md](../technical_reference/CAMERA_DEVELOPER_GUIDE.md) | Backend devs | Implementation details |
| [CAMERA_FRONTEND_INTEGRATION.md](../technical_reference/CAMERA_FRONTEND_INTEGRATION.md) | Frontend devs | React integration |
