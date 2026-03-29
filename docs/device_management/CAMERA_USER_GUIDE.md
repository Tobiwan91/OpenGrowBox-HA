# Camera System - User Guide

## Overview

The OpenGrowBox Camera System provides comprehensive grow room monitoring through three core features:

- **Live Streaming** - Watch your plants in real-time
- **Daily Snapshots** - Automatic photos at scheduled times
- **Timelapse Videos** - Create stunning growth progression videos

This guide covers all features from a user perspective. No technical knowledge required.

---

## Getting Started

### Prerequisites

Before using the camera system, ensure you have:

1. **Camera Device** - Any camera configured in Home Assistant (IP camera, USB camera, ESP32 camera, etc.)
2. **Camera Added to OGB** - Camera must be assigned to your grow room
3. **Storage Space** - At least 1GB free space for photos and videos
4. **FFmpeg Installed** - Usually included with Home Assistant (needed for video generation)

### Quick Setup Checklist

- [ ] Camera visible in Home Assistant
- [ ] Camera assigned to OGB room
- [ ] CameraCard shows in your dashboard
- [ ] Live stream or still image appears
- [ ] Storage directories created automatically

### Accessing the Camera

1. Open your OpenGrowBox dashboard
2. Navigate to the room with your camera
3. Locate the **CameraCard** component
4. Select your camera from the dropdown if you have multiple

---

## Live Streaming

### How It Works

The camera system provides real-time video streaming with automatic fallback:

1. **Primary** - HLS video streaming for smooth playback
2. **Fallback** - Still images refreshed every 5 seconds if streaming unavailable
3. **Automatic** - System switches between modes automatically

### Stream Status Indicators

| Status      | Meaning                                |
|-------------|----------------------------------------|
| Streaming   | Live video is playing                  |
| Connecting  | Establishing connection                |
| Still Image | Showing photos (streaming unavailable) |
| Error       | Connection failed                      |

### Troubleshooting Streaming Issues

**"No Cameras Found"**
- Wait 1-2 seconds for data to load (especially after browser refresh)
- Verify camera is configured in Home Assistant
- Ensure camera is assigned to the correct room

**Black Screen or No Stream**
- Camera may not support HLS streaming
- System will automatically show still images instead
- Check camera is working in Home Assistant's dashboard

**"Stream initialization failed"**
- This is expected for cameras without streaming support
- Fallback to still images happens automatically
- Still images work fine for most monitoring needs

---

## Daily Snapshots

Daily snapshots automatically capture photos at a consistent time each day, perfect for tracking plant progress over time.

### Setting Up Daily Snapshots

1. Open the **CameraCard** in your dashboard
2. Click the **"Config"** tab
3. Toggle **"Enable Daily Snapshots"** to ON
4. Set your preferred **Snapshot Time** (default: 09:00)
5. The system automatically schedules captures

### Choosing Snapshot Time

Pick a time when:
- Lights are ON (for best image quality)
- You're unlikely to be working in the grow space
- Consistent timing helps with day-over-day comparisons

### Browsing Daily Photos

1. Go to the **Daily** tab in CameraCard
2. Use arrow buttons to browse by date
3. Most recent photo displays automatically
4. Dates with photos appear highlighted

### Managing Storage

**View Storage Usage**
- Each photo is typically 500KB - 2MB
- 30 days of daily snapshots ≈ 15-60 MB

**Delete Individual Photos**
1. Browse to the photo you want to remove
2. Click the trash/delete button
3. Confirm the deletion
4. Photo is permanently removed

**Delete All Daily Photos**
1. Open the **Config** tab
2. Click **"Delete All Photos"**
3. Confirm the deletion
4. All daily photos are permanently removed

**Warning**: Deletions cannot be undone. Consider downloading important photos first.

### Downloading Photos

**Download Single Photo**
1. Browse to the desired photo
2. Click the download button
3. Photo saves to your device

**Download Date Range as ZIP**
1. Open the **Daily** tab
2. Click **"Download ZIP"**
3. Select start and end dates
4. Click **"Generate ZIP"**
5. File downloads automatically when ready

---

## Timelapse Creation

Timelapses compress days or weeks of growth into minutes of video, creating stunning visual progress records.

### Understanding Timelapse Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   CONFIGURE     │ ──> │    RECORD       │ ──> │    GENERATE     │
│                 │     │                 │     │                 │
│ Set dates       │     │ Capture images  │     │ Create video    │
│ Set interval    │     │ automatically   │     │ or ZIP          │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Step 1: Configure Settings

1. Open the **CameraCard**
2. Click the **"Config"** tab
3. Set the following:

**Start Date & Time**
- When capturing should begin
- Can be in the future (scheduled start)
- Or set to now for immediate start

**End Date & Time**
- When capturing should stop
- Must be after start date
- Longer periods = more images = longer videos

**Capture Interval**
- How often to take a photo
- Shorter intervals = smoother video but more storage
- See interval recommendations below

**Output Format**
- **MP4 Video** - Watchable video file (recommended)
- **ZIP Archive** - Collection of original images

### Recommended Intervals

| Interval   | Best For            | Storage/Day |
|------------|---------------------|-------------|
| 5 minutes  | Detailed monitoring | ~150 MB     |
| 10 minutes | Balanced recording  | ~75 MB      |
| 15 minutes | Standard timelapse  | ~50 MB      |
| 30 minutes | Long-term tracking  | ~25 MB      |
| 1 hour     | Minimal monitoring  | ~12 MB      |

**Tip**: 10-15 minute intervals work well for most grows. You can always generate a video from fewer images, but you can't add images you didn't capture.

### Step 2: Start Recording

**Immediate Start**
1. Set Start Date to current time
2. Set End Date to when you want to stop
3. Click **"Start Recording"**
4. Recording begins within one interval period

**Scheduled Start**
1. Set Start Date to future time
2. Set End Date
3. Click **"Start Recording"**
4. Status shows "Scheduled" until start time

### Night Mode

By default, timelapse only captures when lights are ON. This avoids filling storage with dark images.

**Night Mode Indicator**
- Moon icon appears when lights are off
- "Night Mode - Auto-skipping captures" message shows
- Captures resume when lights turn on

**Enable Night Capture**
1. Open timelapse configuration
2. Enable "Capture at Night" option
3. Captures will continue during dark periods

### Step 3: Monitor Recording

While recording, you'll see:

- **Recording Status** - Active, Scheduled, or Night Mode
- **Image Count** - Total photos captured
- **Start Time** - When recording began
- **Progress** - Visual indicator of recording state

### Step 4: Stop Recording

**Manual Stop**
1. Click **"Stop Recording"**
2. Confirm the stop
3. All captured images are preserved

**Automatic Stop**
- Recording stops automatically at End Date
- Images are preserved for video generation

### Step 5: Generate Video

1. Ensure recording is stopped
2. Click **"Generate Timelapse"**
3. Select output format (MP4 or ZIP)
4. Watch the progress bar

**Generation Timeline**
- 100 images: ~30-60 seconds
- 500 images: ~2-5 minutes
- 1000+ images: ~5-15 minutes

**Progress Updates**
- 0%: Generation started
- 25%: Processing images
- 50%: Encoding video
- 100%: Complete

### Downloading Your Video

When generation completes:
- Video downloads automatically to your browser
- Filename includes camera name and timestamp
- Also available in the timelapse output folder

### Managing Timelapse Data

**View Captured Images**
1. Open **Config** tab
2. See total image count
3. Browse available timelapses

**Delete Source Images**
- Click **"Delete All Timelapse Images"**
- Removes raw images only
- Generated videos are preserved

**Delete Output Videos**
- Click **"Delete All Output Files"**
- Removes generated MP4/ZIP files
- Raw images are preserved

**Tip**: Generate your video before deleting source images. Once deleted, you cannot regenerate the video.

---

## Storage Management

### Where Files Are Stored

Your camera files are organized automatically:

```
Home Assistant Config/
└── ogb_data/
    └── [room_name]_img/
        └── [camera_name]/
            ├── daily/          # Daily snapshots
            └── timelapse/      # Timelapse images
```

Generated videos are stored in:
```
Home Assistant Config/
└── www/
    └── ogb_data/
        └── [room_name]_img/
            ├── timelapse_output/   # Generated videos
            └── daily_output/       # ZIP archives
```

### Storage Planning

**Estimate Your Needs**

| Use Case                    | Daily  | Weekly  | Monthly |
|-----------------------------|--------|---------|---------|
| Daily snapshots only        | ~2 MB  | ~14 MB  | ~60 MB  |
| Timelapse (15 min interval) | ~50 MB | ~350 MB | ~1.5 GB |
| Both combined               | ~52 MB | ~364 MB | ~1.6 GB |

**Recommendations**
- Monitor available disk space weekly
- Generate videos and delete source images periodically
- Download important videos to external storage

### Backup Strategies

**Manual Backup**
- Use Samba share to copy files
- Download ZIP archives through the UI
- Save to external drive or cloud storage

**What to Backup**
- Daily photos (for growth records)
- Generated timelapse videos
---

## Troubleshooting

### Common Issues

**Daily Snapshots Not Appearing**
- Verify "Enable Daily Snapshots" is ON
- Check scheduled time is correct
- Ensure camera is working in Home Assistant
- Try a manual capture test

**Timelapse Won't Start**
- Verify End Date is after Start Date
- Check camera is accessible
- Ensure sufficient disk space

**Video Generation Fails**
- Ensure FFmpeg is installed
- Verify you have captured images (100+ recommended)
- Check available disk space
- Try ZIP format as alternative

**Photos Not Loading**
- Wait a few seconds for large images
- Refresh the page
- Check browser console for errors

### Error Messages

| Message                               | Meaning               | Solution                                 |
|---------------------------------------|-----------------------|------------------------------------------|
| "No authentication token"             | Login expired         | Refresh page or re-login                 |
| "Camera doesn't support HLS"          | Streaming unavailable | Falls back to still images automatically |
| "Failed to fetch image: 401"          | Permission issue      | Re-login to refresh credentials          |
| "Generation failed: subprocess error" | FFmpeg problem        | Check FFmpeg installation                |

### Getting Help

**Before Reporting Issues**
1. Check Home Assistant logs for errors
2. Open browser console (F12) for frontend errors
3. Note your HA version, OGB version, and camera type

**Where to Get Help**
- OGB Documentation
- GitHub Issues
- Home Assistant Community Forums
- OGB Discord

---

## Best Practices

### For Best Results

**Camera Placement**
- Position for full plant visibility
- Avoid direct light into lens
- Ensure stable mounting

**Lighting**
- Good lighting improves image quality
- Consistent lighting helps timelapse smoothness
- Avoid shadows across grow area

**Interval Selection**
- Faster-growing plants: Shorter intervals (5-10 min)
- Slower growth stages: Longer intervals (15-30 min)
- Flowering stage: 15 min intervals work well

**Storage Management**
- Weekly: Check disk space
- Monthly: Generate videos, delete old images
- Quarterly: Backup important content

---

## FAQ

**How many cameras can I use?**
No hard limit. Practical limit is 4-6 per room due to UI space and bandwidth.

**Can I use outdoor cameras?**
Yes, any Home Assistant camera entity works with OGB.

**What's the maximum timelapse duration?**
Limited only by disk space. 30-60 days is practical for most setups.

**Do timelapses impact Home Assistant performance?**
Minimal impact during recording. Video generation uses CPU for 2-15 minutes.

**What happens if Home Assistant restarts?**
Recording resumes automatically if end time hasn't passed. No images are lost.

**Can I change interval while recording?**
Yes, but changes apply on the next capture cycle. Existing images are preserved.

**Can I access photos outside OGB?**
Yes, via Samba share, SSH, or File Editor add-on at the paths listed above.

**Do daily snapshots and timelapse work together?**
Yes, they're independent systems. You can use both simultaneously.

---

## Glossary

| Term               | Definition                                          |
|--------------------|-----------------------------------------------------|
| **HLS**            | HTTP Live Streaming - video streaming technology    |
| **Interval**       | Time between timelapse photo captures               |
| **FFmpeg**         | Video processing tool used for timelapse generation |
| **Daily Snapshot** | Single photo taken at scheduled time each day       |
| **Timelapse**      | Video created from sequential photos                |
| **Night Mode**     | Period when grow lights are off                     |

---

## Document Information

**Version**: 2.0
**Last Updated**: 2026-03-29
**Applies To**: OpenGrowBox Camera System (Modular Architecture)

---

## Related Documentation

- **Architecture**: [CAMERA_ARCHITECTURE.md](../specialized_systems/CAMERA_ARCHITECTURE.md) - System design overview
- **Developer Guide**: [CAMERA_DEVELOPER_GUIDE.md](../technical_reference/CAMERA_DEVELOPER_GUIDE.md) - Technical implementation
- **Frontend Integration**: [CAMERA_FRONTEND_INTEGRATION.md](../technical_reference/CAMERA_FRONTEND_INTEGRATION.md) - UI development
- **Quick Reference**: [CAMERA_QUICK_REFERENCE.md](CAMERA_QUICK_REFERENCE.md) - Events and file locations
