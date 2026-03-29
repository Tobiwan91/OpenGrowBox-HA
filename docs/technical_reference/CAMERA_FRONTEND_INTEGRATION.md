# Camera Frontend Integration Guide

## Overview

This guide covers the React frontend integration with the OpenGrowBox Camera System. It explains how to build UI components that interact with the camera backend through WebSocket events.

---

## Component Overview

### CameraCard Component

The main camera UI component is `CameraCard.jsx`, which provides:

- **Live View Tab** - Real-time video streaming with HLS.js
- **Daily Tab** - Daily snapshot browsing and management
- **Timelapse Tab** - Recording configuration and video generation

### Component Structure

```
CameraCard/
├── LiveView/           # HLS streaming, still image fallback
├── DailyView/          # Photo browsing, ZIP download
├── TimelapseView/      # Recording controls, generation progress
└── shared/             # Common UI elements
```

---

## Home Assistant Connection

### WebSocket Connection

The frontend uses `home-assistant-js-websocket` for real-time communication:

```javascript
import { subscribeEntities, callService } from 'home-assistant-js-websocket';

// Connection is provided via HomeAssistantContext
const { connection, hass } = useHomeAssistant();
```

### Getting the HA Token

```javascript
const getHaToken = () => {
  // Priority 1: Context accessToken
  if (accessToken) return accessToken;

  // Priority 2: HASS entity state
  if (hass?.states['text.ogb_accesstoken']) {
    return hass.states['text.ogb_accesstoken'].state;
  }

  // Priority 3: localStorage OAuth tokens
  const hassTokens = localStorage.getItem('hassTokens');
  if (hassTokens) {
    return JSON.parse(hassTokens).access_token;
  }

  return '';
};
```

---

## Event Subscriptions

### Subscribing to Camera Events

```javascript
useEffect(() => {
  const subscriptions = [];

  const subscribeToEvents = async () => {
    // Timelapse config response
    const unsub1 = await connection.subscribeEvents(
      (event) => handleTimelapseConfig(event.data),
      'TimelapseConfigResponse'
    );
    subscriptions.push(unsub1);

    // Recording status updates
    const unsub2 = await connection.subscribeEvents(
      (event) => handleRecordingStatus(event.data),
      'CameraRecordingStatus'
    );
    subscriptions.push(unsub2);

    // Generation progress
    const unsub3 = await connection.subscribeEvents(
      (event) => handleGenerationProgress(event.data),
      'TimelapseGenerationProgress'
    );
    subscriptions.push(unsub3);

    // Generation complete
    const unsub4 = await connection.subscribeEvents(
      (event) => handleGenerationComplete(event.data),
      'TimelapseGenerationComplete'
    );
    subscriptions.push(unsub4);

    // Daily photos response
    const unsub5 = await connection.subscribeEvents(
      (event) => handleDailyPhotos(event.data),
      'DailyPhotosResponse'
    );
    subscriptions.push(unsub5);
  };

  subscribeToEvents();

  return () => {
    subscriptions.forEach(unsub => unsub());
  };
}, [connection]);
```

### Key Events to Subscribe

| Event | Purpose | Frequency |
|-------|---------|-----------|
| `TimelapseConfigResponse` | Initial config load | On request |
| `CameraRecordingStatus` | Recording state changes | Every capture |
| `TimelapseGenerationProgress` | Video generation progress | Every 5-10% |
| `TimelapseGenerationComplete` | Generation finished | Once per generation |
| `DailyPhotosResponse` | Daily photos list | On request |
| `DailyPhotoResponse` | Single photo data | On request |
| `DailyZipResponse` | ZIP download ready | On request |
| `ogb_camera_capture_failed` | Capture error | On failure |

---

## Firing Events

### Request Timelapse Configuration

```javascript
const requestTimelapseConfig = async (deviceName) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_get_timelapse_config',
    event_data: {
      device_name: deviceName,
    },
  });
};
```

### Save Timelapse Configuration

```javascript
const saveTimelapseConfig = async (deviceName, config) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_save_timelapse_config',
    event_data: {
      device_name: deviceName,
      config: {
        interval: config.interval,
        startDate: config.startDate,
        endDate: config.endDate,
        format: config.format,
        daily_snapshot_enabled: config.dailyEnabled,
        daily_snapshot_time: config.dailyTime,
        capture_at_night: config.captureAtNight,
      },
    },
  });
};
```

### Start/Stop Timelapse Recording

```javascript
const startTimelapse = async (deviceName) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_start_timelapse',
    event_data: { device_name: deviceName },
  });
};

const stopTimelapse = async (deviceName) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_stop_timelapse',
    event_data: { device_name: deviceName },
  });
};
```

### Generate Timelapse Video

```javascript
const generateTimelapse = async (deviceName, startDate, endDate, format) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_generate_timelapse',
    event_data: {
      device_name: deviceName,
      start_date: startDate,
      end_date: endDate,
      format: format, // 'mp4' or 'zip'
    },
  });
};
```

### Request Daily Photos

```javascript
const requestDailyPhotos = async (deviceName) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_get_daily_photos',
    event_data: { device_name: deviceName },
  });
};
```

### Request Single Daily Photo

```javascript
const requestDailyPhoto = async (deviceName, date) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_get_daily_photo',
    event_data: {
      device_name: deviceName,
      date: date, // 'YYYY-MM-DD' format
    },
  });
};
```

### Delete Daily Photo

```javascript
const deleteDailyPhoto = async (deviceName, date) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_delete_daily_photo',
    event_data: {
      device_name: deviceName,
      date: date,
    },
  });
};
```

### Download Daily ZIP

```javascript
const downloadDailyZip = async (deviceName, startDate, endDate) => {
  await connection.sendMessagePromise({
    type: 'fire_event',
    event_type: 'opengrowbox_download_daily_zip',
    event_data: {
      device_name: deviceName,
      start_date: startDate, // 'YYYY-MM-DD' or null
      end_date: endDate,     // 'YYYY-MM-DD' or null
    },
  });
};
```

---

## Live Streaming

### HLS.js Integration

```javascript
import Hls from 'hls.js';

const LiveStream = ({ cameraEntity, hassUrl, token }) => {
  const videoRef = useRef(null);
  const [streamStatus, setStreamStatus] = useState('idle');
  const hlsRef = useRef(null);

  useEffect(() => {
    const startStream = async () => {
      setStreamStatus('connecting');

      try {
        // Request stream URL from HA
        const streamResponse = await connection.sendMessagePromise({
          type: 'camera/stream',
          entity_id: cameraEntity,
        });

        if (streamResponse?.url && Hls.isSupported()) {
          const hls = new Hls({
            maxBufferLength: 30,
            maxMaxBufferLength: 60,
          });

          hls.loadSource(streamResponse.url);
          hls.attachMedia(videoRef.current);

          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            setStreamStatus('streaming');
          });

          hls.on(Hls.Events.ERROR, () => {
            setStreamStatus('error');
            // Fall back to still images
          });

          hlsRef.current = hls;
        }
      } catch (error) {
        setStreamStatus('error');
        // Fall back to still images
      }
    };

    startStream();

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
      }
    };
  }, [cameraEntity, connection]);

  return <video ref={videoRef} autoPlay muted playsInline />;
};
```

### Still Image Fallback

```javascript
const StillImageFallback = ({ cameraEntity, hassUrl, token }) => {
  const [imageUrl, setImageUrl] = useState(null);

  useEffect(() => {
    const fetchImage = async () => {
      try {
        const response = await fetch(
          `${hassUrl}/api/camera_proxy/${cameraEntity}`,
          {
            headers: { Authorization: `Bearer ${token}` },
          }
        );

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        setImageUrl(url);
      } catch (error) {
        console.error('Failed to fetch camera image:', error);
      }
    };

    fetchImage();
    const interval = setInterval(fetchImage, 5000); // Refresh every 5s

    return () => {
      clearInterval(interval);
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [cameraEntity, hassUrl, token]);

  return imageUrl ? <img src={imageUrl} alt="Camera" /> : <div>Loading...</div>;
};
```

---

## State Management

### Recording Status State

```javascript
const [recordingStatus, setRecordingStatus] = useState({
  isRecording: false,
  isScheduled: false,
  isNightMode: false,
  imageCount: 0,
  startTime: null,
  captureFailed: false,
});

const handleRecordingStatus = (data) => {
  if (data.camera_entity === selectedCamera) {
    setRecordingStatus({
      isRecording: data.is_recording,
      isScheduled: data.is_scheduled || false,
      isNightMode: data.is_night_mode || false,
      imageCount: data.image_count,
      startTime: data.start_time,
      captureFailed: data.capture_failed || false,
    });
  }
};
```

### Generation Progress State

```javascript
const [generation, setGeneration] = useState({
  active: false,
  progress: 0,
  status: 'idle',
});

const handleGenerationProgress = (data) => {
  if (data.device_name === selectedCamera) {
    setGeneration({
      active: true,
      progress: data.progress,
      status: data.status,
    });
  }
};

const handleGenerationComplete = (data) => {
  if (data.device_name === selectedCamera) {
    setGeneration({ active: false, progress: 100, status: 'complete' });

    if (data.success && data.download_url) {
      // Trigger download
      window.open(data.download_url, '_blank');
    } else if (data.error) {
      // Show error message
      console.error('Generation failed:', data.error);
    }
  }
};
```

### Daily Photos State

```javascript
const [dailyPhotos, setDailyPhotos] = useState({
  photos: [],
  count: 0,
  currentPhoto: null,
  currentImageData: null,
});

const handleDailyPhotos = (data) => {
  if (data.camera_entity === selectedCamera) {
    setDailyPhotos({
      photos: data.photos,
      count: data.count,
      currentPhoto: data.photos[0] || null,
    });
  }
};

const handleDailyPhoto = (data) => {
  if (data.success) {
    setDailyPhotos(prev => ({
      ...prev,
      currentImageData: data.image_data,
    }));
  }
};
```

---

## Cleanup Patterns

### Blob URL Cleanup

```javascript
useEffect(() => {
  let blobUrl = null;

  const fetchImage = async () => {
    const blob = await fetch(/* ... */).then(r => r.blob());
    blobUrl = URL.createObjectURL(blob);
    setImageUrl(blobUrl);
  };

  fetchImage();

  return () => {
    if (blobUrl) {
      URL.revokeObjectURL(blobUrl);
    }
  };
}, [dependencies]);
```

### Event Subscription Cleanup

```javascript
useEffect(() => {
  const unsubscriptions = [];

  const setupSubscriptions = async () => {
    const unsub1 = await connection.subscribeEvents(handler1, 'Event1');
    const unsub2 = await connection.subscribeEvents(handler2, 'Event2');
    unsubscriptions.push(unsub1, unsub2);
  };

  setupSubscriptions();

  return () => {
    unsubscriptions.forEach(unsub => unsub());
  };
}, [connection]);
```

### HLS.js Cleanup

```javascript
useEffect(() => {
  const hls = new Hls();

  // ... setup

  return () => {
    hls.destroy();
  };
}, [dependencies]);
```

---

## Event Payload Schemas

### TimelapseConfigResponse

```typescript
interface TimelapseConfigResponse {
  device_name: string;
  storage_path: string;
  current_config: {
    interval: string;
    StartDate: string;
    EndDate: string;
    OutPutFormat: 'mp4' | 'zip';
    daily_snapshot_enabled: boolean;
    daily_snapshot_time: string;
    capture_at_night: boolean;
  };
  available_timelapses: Array<{
    folder: string;
    path: string;
    image_count: number;
  }>;
  tl_active: boolean;
  tl_start_time: string | null;
  tl_image_count: number;
  last_capture_time: string | null;
}
```

### CameraRecordingStatus

```typescript
interface CameraRecordingStatus {
  room: string;
  camera_entity: string;
  is_recording: boolean;
  is_scheduled?: boolean;
  scheduled_start?: string;
  scheduled_end?: string;
  image_count: number;
  start_time: string | null;
  last_capture_time: string | null;
  is_night_mode: boolean;
  capture_at_night_enabled: boolean;
  capture_failed?: boolean;
}
```

### TimelapseGenerationProgress

```typescript
interface TimelapseGenerationProgress {
  device_name: string;
  progress: number;  // 0-100
  status: 'scanning' | 'preparing' | 'creating_zip' | 'encoding_video';
  file_count?: number;
}
```

### TimelapseGenerationComplete

```typescript
interface TimelapseGenerationComplete {
  device_name: string;
  success: boolean;
  filename?: string;
  format?: 'mp4' | 'zip';
  frame_count?: number;
  download_url?: string;
  file_size?: number;
  download_method?: 'url';
  estimated_time?: string;
  estimated_space?: string;
  error?: string;
}
```

### DailyPhotosResponse

```typescript
interface DailyPhotosResponse {
  camera_entity: string;
  photos: Array<{
    date: string;
    filename: string;
  }>;
  storage_path: string;
  count: number;
}
```

### DailyPhotoResponse

```typescript
interface DailyPhotoResponse {
  camera_entity: string;
  success: boolean;
  date: string;
  filename: string;
  image_data: string;  // Base64 encoded
  timestamp: string;
  error?: string;
}
```

---

## Common UI Patterns

### Recording Status Indicator

```jsx
const RecordingIndicator = ({ status }) => {
  if (status.isNightMode) {
    return (
      <Badge icon={<MdNightlight />}>
        Night Mode - Auto-skipping captures
      </Badge>
    );
  }

  if (status.isScheduled) {
    return (
      <Badge variant="warning">
        Scheduled: {formatTime(status.scheduledStart)}
      </Badge>
    );
  }

  if (status.isRecording) {
    return (
      <Badge variant="success">
        Recording: {status.imageCount} images
      </Badge>
    );
  }

  return <Badge variant="default">Not Recording</Badge>;
};
```

### Progress Bar

```jsx
const GenerationProgress = ({ generation }) => {
  if (!generation.active && generation.status === 'idle') {
    return null;
  }

  return (
    <div>
      <ProgressBar value={generation.progress} max={100} />
      <span>
        {generation.status === 'encoding_video' ? 'Encoding video...' :
         generation.status === 'creating_zip' ? 'Creating ZIP...' :
         'Processing...'}
      </span>
    </div>
  );
};
```

---

## Related Documentation

- **Architecture**: [CAMERA_ARCHITECTURE.md](../specialized_systems/CAMERA_ARCHITECTURE.md)
- **User Guide**: [CAMERA_USER_GUIDE.md](../device_management/CAMERA_USER_GUIDE.md)
- **Developer Guide**: [CAMERA_DEVELOPER_GUIDE.md](CAMERA_DEVELOPER_GUIDE.md)
- **Quick Reference**: [CAMERA_QUICK_REFERENCE.md](../device_management/CAMERA_QUICK_REFERENCE.md)
