# Camera Developer Guide - Backend Implementation

## Overview

This guide covers the backend implementation of the OpenGrowBox Camera System. The system has been refactored into a modular architecture with 7 focused modules.

For system architecture, see [CAMERA_ARCHITECTURE.md](../specialized_systems/CAMERA_ARCHITECTURE.md).

---

## Module Reference

### Camera (Main Coordinator)

**File**: `Camera/__init__.py`
**Class**: `Camera(Device)`

The main Camera class extends the base `Device` class and serves as the coordinator for all camera functionality.

**Responsibilities**:
- Device initialization and lifecycle
- Module instantiation and dependency injection
- PlantsView state management callbacks
- Internal event handling (StartTL, NeedViewPlant)

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `deviceInit(entitys)` | Store camera entities, set capabilities |
| `async init()` | Initialize storage, restore state, register handlers |
| `async startTL(resume, oldest_start_time)` | Start timelapse from plantsView config |
| `async async_cleanup()` | Cancel all scheduled tasks on shutdown |

**Initialization Flow**:
1. `__init__` creates all module instances with dependency injection
2. `deviceInit` stores entities and sets capabilities
3. `init` hydrates state, creates directories, restores timelapses

---

### CameraCapture

**File**: `Camera/capture.py`
**Class**: `CameraCapture`

Handles image capture from Home Assistant camera entities with retry logic.

**Responsibilities**:
- Fetch images from HA camera API
- Implement exponential backoff retry
- Cache recent captures
- Emit failure events

**Configuration**:
```python
DEFAULT_RETRY_DELAYS = [5, 15, 30]  # seconds
DEFAULT_MAX_RETRIES = 3
```

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `async get_ha_camera_image(entity_id)` | Single capture attempt via HA API |
| `async capture_with_retry(entity_id, ...)` | Capture with exponential backoff |
| `async capture_daily_snapshot(entity_id)` | Daily snapshot with retry |
| `async capture_timelapse_image(entity_id)` | Timelapse capture with retry |
| `get_cached_image(max_age_minutes)` | Retrieve cached image if valid |

**Retry Pattern**:
- Attempt 1: Immediate
- Attempt 2: Wait 5 seconds
- Attempt 3: Wait 15 seconds
- Attempt 4: Wait 30 seconds
- On failure: Emit `ogb_camera_capture_failed` event

---

### CameraScheduler

**File**: `Camera/scheduling.py`
**Class**: `CameraScheduler`

Manages timelapse and daily snapshot scheduling using Home Assistant timers.

**Responsibilities**:
- Start/stop timelapse recording
- Schedule daily snapshots
- Handle HA restart recovery
- Check plant day/night cycle

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `async start_timelapse(start_dt, end_dt, resume)` | Begin interval capture |
| `async stop_timelapse(user_initiated)` | End recording, emit completion |
| `async schedule_daily_snapshot()` | Schedule next daily capture |
| `async restore_timelapse_after_restart()` | Resume after HA restart |
| `async cleanup()` | Cancel all timers |

**Callback Pattern**:
The scheduler receives callbacks rather than direct references:
- `get_plants_view` - Read state from datastore
- `set_plants_view` - Write state to datastore
- `capture_callback` - Trigger image capture
- `emit_recording_status` - Emit status events

**Night Mode Handling**:
```python
is_plant_day = self.data_store.getDeep("isPlantDay.islightON")
capture_at_night = plants_view.get("capture_at_night", False)

if not is_plant_day and not capture_at_night:
    # Skip capture, emit night mode status
    await self._emit_recording_status(is_recording=True, is_night_mode=True)
    return
```

---

### CameraStorage

**File**: `Camera/storage.py`
**Class**: `CameraStorage`

Handles all file I/O operations with path validation and executor wrapping.

**Responsibilities**:
- Directory management and creation
- Image save/delete operations
- ZIP file creation
- Path traversal protection
- State hydration from disk

**Path Methods**:

| Method | Returns |
|--------|---------|
| `get_base_path()` | `/config/ogb_data/{room}_img/{camera}` |
| `get_daily_path()` | `{base}/daily` |
| `get_timelapse_path()` | `{base}/timelapse` |
| `get_output_path()` | `/config/www/ogb_data/{room}_img/timelapse_output` |

**Path Validation Pattern**:
```python
def validate_storage_path(self, subdirectory, base_path=None):
    target_path = os.path.join(storage_path, subdirectory)
    target_path_resolved = os.path.realpath(target_path)
    storage_path_resolved = os.path.realpath(storage_path)

    if not target_path_resolved.startswith(storage_path_resolved):
        raise ValueError(f"Path traversal attempt detected: {target_path}")
```

**Executor Wrapping Pattern**:
```python
async def save_image(self, path, image_data):
    await self.hass.async_add_executor_job(
        self._sync_save_image, path, image_data
    )
```

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `async initialize_storage_paths()` | Create directories on startup |
| `async save_image(path, image_data)` | Save base64 image to disk |
| `async save_daily_photo(image_data)` | Save with YYYY-MM-DD_HHMMSS.jpg naming |
| `async delete_all_photos_in_directory(path)` | Bulk delete with validation |
| `async hydrate_plants_view_from_disk(callback)` | Load state from JSON file |

---

### VideoGenerator

**File**: `Camera/video_generator.py`
**Class**: `VideoGenerator`

Creates timelapse videos using FFmpeg with hardware acceleration detection.

**Responsibilities**:
- Scan timelapse directory for images
- Detect hardware acceleration (VAAPI, NVENC, V4L2)
- Generate MP4 videos with FFmpeg
- Create ZIP archives
- Track and emit generation progress

**Hardware Acceleration Priority**:
1. V4L2 M2M (Raspberry Pi)
2. VAAPI (Intel/AMD)
3. NVENC (NVIDIA)
4. Software encoding (libx264 fallback)

**Memory-Aware Limits**:
```python
def _get_max_file_size(self):
    # Try psutil first
    mem = psutil.virtual_memory()
    max_mb = int(mem.available * 0.7)  # 70% of available

    # Fallback to /proc/meminfo
    # Final fallback: 200MB default
```

**Dynamic FPS Calculation**:
```python
if num_images <= 10: fps = 2
elif num_images <= 20: fps = 3
elif num_images <= 30: fps = 4
else: fps = 6
```

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `detect_hardware_acceleration()` | Return (encoder, pix_fmt, extra_params) |
| `async generate_timelapse_video(...)` | Main generation entry point |
| `async handle_generate_timelapse(event, ...)` | Event handler wrapper |
| `async cancel_generation()` | Abort active generation |

**Progress Tracking**:
- Emit `TimelapseGenerationProgress` events during generation
- Status values: `scanning`, `preparing`, `creating_zip`, `encoding_video`, `complete`, `error`
- Progress: 0-100 percentage

---

### CameraEventHandlers

**File**: `Camera/handlers.py`
**Class**: `CameraEventHandlers`

Routes Home Assistant bus events to appropriate module methods.

**Responsibilities**:
- Register HA bus listeners
- Validate device targeting
- Route events to handlers
- Emit response events

**Event Registration**:
```python
def register_all(self):
    self.hass.bus.async_listen("opengrowbox_get_timelapse_config", handler)
    self.hass.bus.async_listen("opengrowbox_save_timelapse_config", handler)
    self.hass.bus.async_listen("opengrowbox_generate_timelapse", handler)
    # ... more events
```

**Device Targeting Pattern**:
```python
def _is_device_for_event(self, device_name):
    normalized = str(device_name).strip().lower()
    return normalized in {
        self.device_name.lower(),
        self.camera_entity_id.lower(),
        f"camera.{self.device_name}".lower(),
    }
```

**Handled Events**:

| Event | Handler Method |
|-------|----------------|
| `opengrowbox_get_timelapse_config` | `_handle_get_timelapse_config` |
| `opengrowbox_save_timelapse_config` | `_handle_save_timelapse_config` |
| `opengrowbox_generate_timelapse` | `_handle_generate_timelapse` |
| `opengrowbox_start_timelapse` | `_handle_start_timelapse` |
| `opengrowbox_stop_timelapse` | `_handle_stop_timelapse` |
| `opengrowbox_get_daily_photos` | `_handle_get_daily_photos` |
| `opengrowbox_get_daily_photo` | `_handle_get_daily_photo` |
| `opengrowbox_delete_daily_photo` | `_handle_delete_daily_photo` |
| `opengrowbox_delete_all_daily` | `_handle_delete_all_daily` |
| `opengrowbox_download_daily_zip` | `_handle_download_daily_zip` |
| `opengrowbox_delete_all_timelapse` | `_handle_delete_all_timelapse` |
| `opengrowbox_delete_all_timelapse_output` | `_handle_delete_all_timelapse_output` |
| `opengrowbox_get_timelapse_photos` | `_handle_get_timelapse_photos` |
| `opengrowbox_user_needs_image` | `_handle_user_needs_image` |

---

### Utils (Pure Functions)

**File**: `Camera/utils.py`

Pure utility functions with no class dependencies. Easily testable in isolation.

**Functions**:

| Function | Purpose |
|----------|---------|
| `parse_datetime_value(value)` | Parse ISO datetime strings to timezone-aware datetime |
| `to_storage_iso(dt_value)` | Serialize datetime to UTC ISO with Z suffix |
| `sanitize_filename_part(value, fallback)` | Convert text to filesystem-safe filename |

**DateTime Parsing**:
- Handles ISO format with Z suffix
- Fixes malformed legacy strings (e.g., `+00:00Z`)
- Falls back to legacy localized formats

---

## Event System

### Events Emitted (Backend → Frontend)

| Event | When | Payload Keys |
|-------|------|--------------|
| `TimelapseConfigResponse` | Config requested | `current_config`, `tl_active`, `tl_image_count` |
| `TimelapseConfigSaved` | Config updated | `config` |
| `TimelapseGenerationStarted` | Generation begins | `start_date`, `end_date`, `format` |
| `TimelapseGenerationProgress` | During generation | `progress`, `status`, `file_count` |
| `TimelapseGenerationComplete` | Generation done | `success`, `download_url`, `file_size` |
| `CameraRecordingStatus` | Recording state change | `is_recording`, `image_count`, `is_night_mode` |
| `TimelapseCompleted` | Recording ended | `total_images`, `duration`, `user_initiated` |
| `DailyPhotosResponse` | Photos listed | `photos`, `count`, `storage_path` |
| `DailyPhotoResponse` | Single photo | `image_data`, `date`, `filename` |
| `DailyZipResponse` | ZIP created | `download_url`, `photo_count`, `total_size` |
| `ogb_camera_capture_failed` | Capture error | `error`, `retry_count`, `capture_type` |
| `ogb_camera_daily_photo_captured` | Daily success | `date`, `filename`, `path` |
| `ogb_camera_photo_deleted` | Photo deleted | `date`, `filename` |
| `ogb_camera_all_daily_deleted` | Bulk delete | `deleted_count` |

### Events Received (Frontend → Backend)

All received events use the `opengrowbox_` prefix.

---

## DataStore Integration

### PlantsView Structure

Camera state is stored in the room's datastore under `plantsView`:

```
plantsView: {
    isTimeLapseActive: boolean,
    TimeLapseIntervall: string,      // "300", "600", etc.
    StartDate: string,               // "2026-03-29T12:00:00Z"
    EndDate: string,                 // "2026-04-15T12:00:00Z"
    OutPutFormat: "mp4" | "zip",
    tl_image_count: number,
    daily_snapshot_enabled: boolean,
    daily_snapshot_time: string,     // "09:00"
    capture_at_night: boolean
}
```

### State Persistence

The camera system triggers state saves via the `SaveState` event:

```python
await self.event_manager.emit("SaveState", {
    "source": "Camera",
    "device": self.device_name,
    "action": "start_recording"  # or "stop_recording", etc.
})
```

---

## Error Handling Patterns

### Capture Failure Handling

```python
if not image_data:
    await self.event_manager.emit("ogb_camera_capture_failed", {
        "device": self.device_name,
        "room": self.in_room,
        "error": f"Failed after {max_retries} retry attempts",
        "retry_count": max_retries,
        "capture_type": "daily" | "timelapse",
    }, haEvent=True)
```

### Path Validation

```python
try:
    target_path, target_resolved, storage_path, storage_resolved = \
        self.validate_storage_path("daily")
except ValueError as e:
    _LOGGER.error(f"Path validation failed: {e}")
    return {"success": False, "reason": "Path validation failed"}
```

### Generation Error Recovery

```python
try:
    # Generation logic
except Exception as e:
    self.generation_status = "error"
    await self.event_manager.emit("TimelapseGenerationComplete", {
        "device_name": camera_entity_id,
        "success": False,
        "error": str(e),
    }, haEvent=True)
finally:
    self.generation_active = False
```

---

## Testing Guide

### Unit Testing Utils

The `utils.py` module contains pure functions that are easily testable:

```python
# Test datetime parsing
result = parse_datetime_value("2026-03-29T12:00:00Z")
assert result.tzinfo is not None

# Test filename sanitization
result = sanitize_filename_part("Blue Dream #1!")
assert result == "blue_dream_1"
```

### Integration Testing

Key integration points to test:

1. **Capture Flow**: Mock HA camera API, verify retry logic
2. **Scheduling**: Use `asyncio` time mocking for timer tests
3. **Storage**: Use temp directories, verify path validation
4. **Events**: Subscribe to events, verify payloads

### Manual Testing Checklist

- [ ] Live streaming displays in CameraCard
- [ ] Daily snapshot creates file at scheduled time
- [ ] Timelapse captures at configured interval
- [ ] Night mode skips captures when expected
- [ ] Video generation completes with progress events
- [ ] HA restart resumes active timelapses
- [ ] Cleanup cancels all scheduled tasks

---

## Debugging

### Enable Debug Logging

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.opengrowbox.OGBController.OGBDevices.Camera: debug
```

### Key Log Points

| Module | Log Message | Meaning |
|--------|-------------|---------|
| Camera | `Camera initialized (storage: ...)` | Startup complete |
| Capture | `Captured successfully (attempt N)` | Retry working |
| Scheduler | `Timelapse capture started` | Recording active |
| Storage | `Path traversal attempt detected` | Security issue |
| VideoGenerator | `Detected VAAPI/NVENC/V4L2` | Hardware accel |
| Handlers | `Sent timelapse config` | Event handled |

---

## Related Documentation

- **Architecture**: [CAMERA_ARCHITECTURE.md](../specialized_systems/CAMERA_ARCHITECTURE.md)
- **User Guide**: [CAMERA_USER_GUIDE.md](../device_management/CAMERA_USER_GUIDE.md)
- **Frontend Integration**: [CAMERA_FRONTEND_INTEGRATION.md](CAMERA_FRONTEND_INTEGRATION.md)
- **Quick Reference**: [CAMERA_QUICK_REFERENCE.md](../device_management/CAMERA_QUICK_REFERENCE.md)
