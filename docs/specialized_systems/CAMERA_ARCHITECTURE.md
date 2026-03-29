# Camera System Architecture

## Overview

The OpenGrowBox Camera System provides comprehensive grow room monitoring through live streaming, automated daily snapshots, and timelapse video creation. The system has been refactored from a monolithic implementation into a **modular architecture** with clear separation of concerns.

### Why the Refactoring?

The original camera implementation was a single large file handling all responsibilities. This created several issues:

- **Testing Difficulty**: Hard to test individual features in isolation
- **Maintenance Burden**: Changes to one feature risked breaking others
- **Code Navigation**: Developers had to scroll through thousands of lines
- **Reusability**: Components couldn't be reused or replaced independently

The modular refactoring addresses these issues by splitting functionality into focused, single-responsibility modules.

---

## Module Breakdown

The camera system consists of **7 modules** organized by responsibility:

```
Camera/
├── __init__.py          # Main Camera class (coordinator)
├── capture.py           # Image capture with retry logic
├── scheduling.py        # Timelapse and daily snapshot scheduling
├── storage.py           # File I/O operations
├── video_generator.py   # FFmpeg video generation
├── handlers.py          # Home Assistant event routing
└── utils.py             # Pure utility functions
```

### Module Responsibilities

| Module               | Class/Type            | Responsibility                            | Dependencies              |
|----------------------|-----------------------|-------------------------------------------|---------------------------|
| `__init__.py`        | `Camera`              | Lifecycle management, module coordination | All modules               |
| `capture.py`         | `CameraCapture`       | Image capture from HA entities            | HA, EventManager          |
| `scheduling.py`      | `CameraScheduler`     | Timelapse & daily snapshot timers         | HA, Storage, DataStore    |
| `storage.py`         | `CameraStorage`       | File operations, path validation          | HA, EventManager          |
| `video_generator.py` | `VideoGenerator`      | MP4/ZIP creation via FFmpeg               | HA, Storage, EventManager |
| `handlers.py`        | `CameraEventHandlers` | HA bus event routing                      | All modules               |
| `utils.py`           | Functions             | DateTime parsing, filename sanitization   | None (pure)               |

---

## Dependency Graph

```
                        ┌─────────────────┐
                        │     Camera      │
                        │   (Coordinator) │
                        └────────┬────────┘
                                 │
           ┌─────────────────────┼─────────────────────┐
           │                     │                     │
           ▼                     ▼                     ▼
    ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
    │   Capture   │      │  Scheduler  │      │   Handlers  │
    └─────────────┘      └──────┬──────┘      └──────┬──────┘
                                │                    │
                                ▼                    │
                         ┌─────────────┐             │
                         │   Storage   │◄────────────┘
                         └──────┬──────┘
                                │
                                ▼
                         ┌─────────────┐
                         │ VideoGen    │
                         └─────────────┘

    ┌─────────────────────────────────────────────────────┐
    │                    External Systems                 │
    ├─────────────┬─────────────┬─────────────┬───────────┤
    │     HA      │  EventMgr   │  DataStore  │   FFmpeg  │
    └─────────────┴─────────────┴─────────────┴───────────┘
```

### Dependency Flow

1. **Camera** is the main entry point - it creates and coordinates all other modules
2. **Handlers** receives HA bus events and routes them to appropriate modules
3. **Scheduler** orchestrates time-based operations (timelapse, daily snapshots)
4. **Capture** handles actual image capture from HA camera entities
5. **Storage** manages all file I/O operations with path validation
6. **VideoGenerator** creates MP4/ZIP output files via FFmpeg
7. **Utils** provides pure helper functions used by multiple modules

---

## Design Patterns Used

### 1. Dependency Injection

All modules receive their dependencies through the constructor rather than creating them internally. This enables:

- **Testability**: Mock dependencies for unit testing
- **Flexibility**: Swap implementations without code changes
- **Loose Coupling**: Modules don't know about each other's internals

```
Camera ──creates──> CameraCapture(hass, device_name, event_manager)
                    CameraScheduler(hass, storage, callbacks...)
                    CameraStorage(hass, event_manager)
                    VideoGenerator(hass, storage, event_manager)
                    CameraEventHandlers(hass, storage, callbacks...)
```

### 2. Event-Driven Architecture

Modules communicate through the EventManager rather than direct method calls:

- **Decoupling**: Sender doesn't need to know about receivers
- **Extensibility**: New listeners can subscribe without modifying senders
- **Observability**: Events can be logged/monitored centrally

**Event Flow Example:**
```
Frontend ──> HA Bus ──> Handlers ──> Scheduler ──> Capture ──> Storage
                            │
                            └──> EventManager.emit("CameraRecordingStatus")
```

### 3. Strategy Pattern

Different behaviors are encapsulated and selected at runtime:

- **Capture Strategy**: Retry with exponential backoff
- **Encoding Strategy**: Hardware acceleration detection (VAAPI, NVENC, V4L2)
- **Output Strategy**: MP4 video or ZIP archive

### 4. Executor Wrapping Pattern

All blocking I/O operations are wrapped in `async_add_executor_job` to prevent blocking the Home Assistant event loop:

- File reads/writes
- Directory listings
- FFmpeg subprocess execution
- ZIP file creation

---

## Key Architectural Decisions

### Decision 1: Module Separation

**Problem**: Single file was too large and mixed concerns.

**Solution**: Split into 7 modules by responsibility.

**Trade-off**: More files to navigate, but each file is focused and testable.

### Decision 2: Pure Utility Module

**Problem**: Utility functions mixed with class methods.

**Solution**: Extract to `utils.py` as pure functions with no class dependencies.

**Trade-off**: Slightly more imports, but functions are independently testable.

### Decision 3: Callback-Based Communication

**Problem**: Circular dependencies between Camera and Scheduler.

**Solution**: Pass callbacks (e.g., `get_plants_view`, `capture_callback`) to Scheduler.

**Trade-off**: Slightly more complex initialization, but avoids circular imports.

### Decision 4: Executor Wrapping for I/O

**Problem**: File operations block the async event loop.

**Solution**: All blocking operations run in thread pool via `async_add_executor_job`.

**Trade-off**: Slight overhead for thread switching, but keeps HA responsive.

---

## Integration Points

### Home Assistant Integration

| Integration Point               | Usage                                 |
|---------------------------------|---------------------------------------|
| `hass.bus.async_listen()`       | Subscribe to frontend events          |
| `hass.async_add_executor_job()` | Run blocking I/O in thread pool       |
| `hass.config.path()`            | Resolve configuration paths           |
| `async_get_image()`             | Capture from HA camera entities       |
| `async_track_time_interval()`   | Schedule recurring timelapse captures |
| `async_track_point_in_time()`   | Schedule daily snapshots              |

### EventManager Integration

The camera system uses OGB's EventManager for inter-component communication:

| Event                         | Direction          | Purpose                    |
|-------------------------------|--------------------|----------------------------|
| `CameraRecordingStatus`       | Backend → Frontend | Real-time recording updates|
| `TimelapseGenerationProgress` | Backend → Frontend | Video generation progress  |
| `TimelapseGenerationComplete` | Backend → Frontend | Generation finished        |
| `ogb_camera_capture_failed`   | Backend → Frontend | Capture error notification |
| `SaveState`                   | Camera → DataStore | Persist configuration      |

### DataStore Integration

Camera configuration is persisted in the room's DataStore under `plantsView`:

```
plantsView: {
    isTimeLapseActive: boolean,
    TimeLapseIntervall: string,      // seconds as string
    StartDate: string,               // ISO datetime
    EndDate: string,                 // ISO datetime
    OutPutFormat: "mp4" | "zip",
    tl_image_count: number,
    daily_snapshot_enabled: boolean,
    daily_snapshot_time: string,     // HH:MM format
    capture_at_night: boolean
}
```

---

## Error Handling and Resilience

### Capture Retry Logic

The `CameraCapture` module implements exponential backoff retry:

```
Attempt 1: Immediate
Attempt 2: Wait 5 seconds
Attempt 3: Wait 15 seconds
Attempt 4: Wait 30 seconds
```

If all attempts fail, an `ogb_camera_capture_failed` event is emitted.

### Path Traversal Protection

All file operations in `CameraStorage` validate paths:

1. Resolve path to absolute using `os.path.realpath()`
2. Verify resolved path starts with allowed base directory
3. Raise `ValueError` if traversal attempt detected

### Memory-Aware Video Generation

The `VideoGenerator` detects available system memory:

1. Try `psutil.virtual_memory()` first
2. Fall back to reading `/proc/meminfo` on Linux
3. Default to 200MB if detection fails
4. Use 70% of available memory as max file size limit

### HA Restart Resilience

The `CameraScheduler.restore_timelapse_after_restart()` method:

1. Checks `plantsView.isTimeLapseActive` on initialization
2. Parses saved `StartDate` and `EndDate`
3. Resumes active timelapses or schedules future ones
4. Skips if end time has already passed

---

## Storage Architecture

### Directory Structure

```
/config/ogb_data/
└── {room_name}_img/
    └── {camera_name}/
        ├── daily/                    # Daily snapshots
        │   ├── 2026-03-29_090000.jpg
        │   └── 2026-03-30_090000.jpg
        └── timelapse/               # Timelapse source images
            ├── camera_20260329_120000.jpg
            └── camera_20260329_120500.jpg

/config/www/ogb_data/
└── {room_name}_img/
    ├── timelapse_output/            # Generated MP4/ZIP files
    │   └── timelapse_camera_20260329.mp4
    └── daily_output/                # Daily ZIP archives
        └── daily_photos_20260329.zip
```

### File Naming Conventions

| Type            | Format                                       | Example                                            |
|-----------------|----------------------------------------------|----------------------------------------------------|
| Daily Snapshot  | `YYYY-MM-DD_HHMMSS.jpg`                      | `2026-03-29_090000.jpg`                            |
| Timelapse Image | `{device}_YYYYMMDD_HHMMSS.jpg`               | `camera1_20260329_120000.jpg`                      |
| Timelapse Video | `timelapse_{device}_{plant}_{timestamp}.mp4` | `timelapse_camera1_blue_dream_20260329_120000.mp4` |
| Timelapse ZIP   | `timelapse_{device}_{plant}_{timestamp}.zip` | `timelapse_camera1_blue_dream_20260329_120000.zip` |

---

## Performance Considerations

### Async File Operations

All file I/O uses `async_add_executor_job` to prevent blocking:

- Directory listing
- File read/write
- ZIP creation
- FFmpeg subprocess execution

### Progress Tracking

Video generation emits progress events every 5-10%:

- Frontend can show progress bars
- User knows system is working
- Timeouts prevent infinite hangs

### Memory Management

- Blob URLs are cleaned up after use
- Video generation uses streaming writes
- Maximum file size limits prevent memory exhaustion

---

## Related Documentation

- **User Guide**: [CAMERA_USER_GUIDE.md](../device_management/CAMERA_USER_GUIDE.md) - End-user feature documentation
- **Developer Guide**: [CAMERA_DEVELOPER_GUIDE.md](../technical_reference/CAMERA_DEVELOPER_GUIDE.md) - Backend implementation details
- **Frontend Integration**: [CAMERA_FRONTEND_INTEGRATION.md](../technical_reference/CAMERA_FRONTEND_INTEGRATION.md) - React component integration
- **Quick Reference**: [CAMERA_QUICK_REFERENCE.md](../device_management/CAMERA_QUICK_REFERENCE.md) - Event and file location reference
