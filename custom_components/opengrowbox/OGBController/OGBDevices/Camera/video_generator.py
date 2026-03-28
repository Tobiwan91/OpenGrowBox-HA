"""
Camera video generator module.

Handles timelapse video creation with FFmpeg.
Includes hardware acceleration detection and progress tracking.
"""

import os
import asyncio
import subprocess
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from homeassistant.util import dt as dt_util

from .utils import parse_datetime_value, sanitize_filename_part
from .storage import CameraStorage

_LOGGER = logging.getLogger(__name__)


class VideoGenerator:
    """Handles timelapse video generation with FFmpeg."""

    def __init__(
        self,
        hass,
        storage: CameraStorage,
        event_manager,
        device_name: str,
        in_room: str,
    ):
        """Initialize video generator.

        Args:
            hass: Home Assistant instance
            storage: CameraStorage instance for file operations
            event_manager: Event manager for emitting events
            device_name: Camera device name
            in_room: Room identifier
        """
        self.hass = hass
        self.storage = storage
        self.event_manager = event_manager
        self.device_name = device_name
        self.in_room = in_room

        # Generation state
        self.generation_active = False
        self.generation_progress = 0
        self.generation_status = "idle"
        self.generation_task = None

        # Rate limiting
        self._generation_lock = asyncio.Lock()
        self._last_generation_time = None
        self._generation_cooldown = 5.0  # seconds

    # =========================================================================
    # Memory Detection
    # =========================================================================

    def _get_max_file_size(self) -> int:
        """Calculate max file size based on available system memory.

        Uses 70% of available memory, with fallback to 200MB.

        Returns:
            Maximum file size in bytes
        """
        DEFAULT_MAX_MB = 200

        try:
            # Try psutil first (most reliable)
            import psutil
            mem = psutil.virtual_memory()
            free_mb = mem.available / (1024 * 1024)
            max_mb = int(free_mb * 0.7)
            _LOGGER.debug(
                f"{self.device_name}: Memory detection via psutil - "
                f"available: {free_mb:.0f}MB, using 70%: {max_mb}MB"
            )
            return max_mb * 1024 * 1024

        except ImportError:
            _LOGGER.debug(f"{self.device_name}: psutil not available, trying /proc/meminfo")
        except Exception as e:
            _LOGGER.warning(f"{self.device_name}: psutil memory detection failed: {e}")

        try:
            # Fallback: Read /proc/meminfo (Linux)
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        # Value is in kB
                        free_kb = int(line.split()[1])
                        free_mb = free_kb / 1024
                        max_mb = int(free_mb * 0.7)
                        _LOGGER.debug(
                            f"{self.device_name}: Memory detection via /proc/meminfo - "
                            f"available: {free_mb:.0f}MB, using 70%: {max_mb}MB"
                        )
                        return max_mb * 1024 * 1024
        except Exception as e:
            _LOGGER.warning(f"{self.device_name}: /proc/meminfo fallback failed: {e}")

        # Final fallback: default 200MB
        _LOGGER.info(
            f"{self.device_name}: Using default max file size: {DEFAULT_MAX_MB}MB"
        )
        return DEFAULT_MAX_MB * 1024 * 1024

    # =========================================================================
    # Hardware Acceleration Detection
    # =========================================================================

    def detect_hardware_acceleration(self) -> Tuple[str, str, List[str]]:
        """Detect available hardware acceleration for video encoding.

        Returns:
            Tuple of (encoder, pix_fmt, extra_params)
            - encoder: ffmpeg video encoder (e.g., h264_v4l2m2m, h264_vaapi)
            - pix_fmt: pixel format (e.g., yuv420p, yuv422p)
            - extra_params: additional ffmpeg parameters
        """
        # Check for V4L2 M2M (Raspberry Pi)
        try:
            result = subprocess.run(
                ["ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=1x1", "-f", "null", "-"],
                capture_output=True, text=True, timeout=5
            )
            # Check if h264_v4l2m2m is available
            result = subprocess.run(
                [
                    "ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=1x1",
                    "-c:v", "h264_v4l2m2m", "-f", "null", "-"
                ],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                _LOGGER.info(
                    f"{self.device_name}: Detected V4L2 M2M hardware acceleration (Raspberry Pi)"
                )
                return ("h264_v4l2m2m", "yuv420p", [])
        except Exception as e:
            _LOGGER.debug(f"{self.device_name}: V4L2 M2M not available: {e}")

        # Check for VAAPI (Intel QuickSync, AMD VCE)
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=1x1",
                    "-c:v", "h264_vaapi", "-f", "null", "-"
                ],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                _LOGGER.info(
                    f"{self.device_name}: Detected VAAPI hardware acceleration (Intel/AMD)"
                )
                return ("h264_vaapi", "yuv420p", ["-vaapi_device", "/dev/dri/renderD128"])
        except Exception as e:
            _LOGGER.debug(f"{self.device_name}: VAAPI not available: {e}")

        # Check for NVENC (NVIDIA)
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=1x1",
                    "-c:v", "h264_nvenc", "-f", "null", "-"
                ],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                _LOGGER.info(
                    f"{self.device_name}: Detected NVENC hardware acceleration (NVIDIA)"
                )
                return ("h264_nvenc", "yuv420p", ["-preset", "fast"])
        except Exception as e:
            _LOGGER.debug(f"{self.device_name}: NVENC not available: {e}")

        # Fallback: Software encoding with optimized settings
        _LOGGER.info(f"{self.device_name}: Using software encoding (libx264)")
        return ("libx264", "yuv420p", [])

    # =========================================================================
    # Logo Resolution
    # =========================================================================

    def _resolve_logo_png_path(self) -> Optional[str]:
        """Resolve static OGB watermark PNG path.

        Returns:
            Path to ogb_tree.png or None if not found
        """
        current_file = os.path.abspath(__file__)
        opengrowbox_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        )
        logo_png_path = os.path.join(opengrowbox_dir, "frontend", "ogb_tree.png")
        if os.path.exists(logo_png_path):
            return logo_png_path
        return None

    # =========================================================================
    # FFmpeg List File Creation
    # =========================================================================

    def _write_ffmpeg_list_file_sync(
        self,
        list_file: str,
        filtered_images: List[Dict[str, Any]],
        interval: int,
    ) -> None:
        """Synchronous helper to write ffmpeg input list file.

        CRITICAL FIX: Duration should be SHORT (0.5s), NOT the interval!
        The interval is for image capture timing, not video playback duration.
        For timelapse, we want each image displayed briefly, then fps determines speed.

        Video length calculation:
        - images / fps = video_duration (seconds)
        - With 20 images and fps=2: 20 / 2 = 10s video
        - With 20 images and fps=4: 20 / 4 = 5s video
        - With 20 images and fps=6: 20 / 6 = ~3.3s video

        Args:
            list_file: Path to output list file
            filtered_images: List of image dicts with 'path' key
            interval: Capture interval (not used for duration, for logging only)
        """
        try:
            with open(list_file, "w") as f:
                f.write(f"# FFmpeg concat list file for timelapse generation\n")
                f.write(
                    f"# Generated by {self.device_name} at {datetime.now()}\n"
                )
                f.write(
                    f"# Image interval: {interval}s, {len(filtered_images)} images\n"
                )
                for img in filtered_images:
                    f.write(f"file '{img['path']}'\n")
                    f.write("duration 0.5\n")  # Each image shows for 0.5s
                # Last frame needs duration too
                if filtered_images:
                    last_img = filtered_images[-1]
                    f.write(f"file '{last_img['path']}'\n")
                    f.write("duration 0.5\n")
        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Failed to write ffmpeg list file: {e}")
            raise

    # =========================================================================
    # Main Video Generation
    # =========================================================================

    async def generate_timelapse_video(
        self,
        start_date: str,
        end_date: str,
        interval: int,
        output_format: str,
        get_plants_view_callback,
        get_current_plant_name_callback,
        camera_entity_id: str,
    ) -> None:
        """Generate timelapse video from stored images.

        Args:
            start_date: Start date in UTC ISO format (YYYY-MM-DDTHH:MM:SSZ)
            end_date: End date in UTC ISO format (YYYY-MM-DDTHH:MM:SSZ)
            interval: Seconds between frames
            output_format: Output format ('mp4' or 'zip')
            get_plants_view_callback: Callback to get plantsView dict
            get_current_plant_name_callback: Callback to get current plant name
            camera_entity_id: Camera entity ID for events
        """
        logo_png_path = None
        try:
            self.generation_active = True
            self.generation_status = "scanning"
            self.generation_progress = 0

            # Initialize filtered_images early to prevent "not defined" errors
            filtered_images = []
            fps = None
            watermark_enabled = False
            logo_png_path = None

            # Use timelapse subdirectory for storage
            timelapse_path = self.storage.get_timelapse_path()

            # Parse dates (UTC ISO format expected: YYYY-MM-DDTHH:MM:SSZ)
            start_dt = parse_datetime_value(start_date)
            end_dt = parse_datetime_value(end_date)

            # Find all images in date range (run in executor to avoid blocking)
            all_images = await self.hass.async_add_executor_job(
                self.storage.scan_timelapse_directory_sync, timelapse_path, start_dt, end_dt
            )

            # Sort by modification time - oldest first for chronological timelapse
            all_images.sort(key=lambda x: x["mtime"])

            if len(all_images) == 0:
                _LOGGER.warning(
                    f"{self.device_name}: No images found for timelapse generation"
                )
                self.generation_status = "error"
                self.generation_active = False
                await self.event_manager.emit("TimelapseGenerationComplete", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "No images found in date range",
                }, haEvent=True)
                return

            # Include all images for both ZIP and video formats
            filtered_images = all_images
            _LOGGER.info(
                f"{self.device_name}: Including all {len(filtered_images)} images for {output_format.upper()} format"
            )

            # Emit early progress info for frontend
            self.generation_status = "preparing"
            self.generation_progress = 5
            await self.event_manager.emit("TimelapseGenerationProgress", {
                "device_name": camera_entity_id,
                "progress": self.generation_progress,
                "status": self.generation_status,
                "file_count": len(filtered_images),
            }, haEvent=True)

            # Create output directory in www folder
            www_path = self.storage.get_output_path()
            await self.hass.async_add_executor_job(
                self.storage._create_output_directory_sync, www_path
            )

            timestamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
            plant_name = get_current_plant_name_callback()
            plant_slug = (
                sanitize_filename_part(plant_name, fallback="plant")
                if plant_name else "plant"
            )
            output_basename = f"timelapse_{self.device_name}_{plant_slug}_{timestamp}"

            if output_format == "zip":
                # Create ZIP of images
                import zipfile
                zip_path = os.path.join(www_path, f"{output_basename}.zip")

                self.generation_status = "creating_zip"
                self.generation_progress = 10
                await self.event_manager.emit("TimelapseGenerationProgress", {
                    "device_name": camera_entity_id,
                    "progress": self.generation_progress,
                    "status": self.generation_status,
                    "file_count": len(filtered_images),
                }, haEvent=True)

                # Create empty ZIP file first
                import zipfile
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    pass

                # Process images in batches
                batch_size = max(1, len(filtered_images) // 10)
                for batch_start in range(0, len(filtered_images), batch_size):
                    batch_end = min(batch_start + batch_size, len(filtered_images))
                    batch = filtered_images[batch_start:batch_end]

                    # Add batch to ZIP in executor
                    await self.hass.async_add_executor_job(
                        self.storage._create_zip_batch_sync, zip_path, batch
                    )

                    # Update progress
                    self.generation_progress = int((batch_end / len(filtered_images)) * 100)

                    # Emit progress
                    await self.event_manager.emit("TimelapseGenerationProgress", {
                        "device_name": camera_entity_id,
                        "progress": self.generation_progress,
                        "status": self.generation_status,
                        "file_count": len(filtered_images),
                    }, haEvent=True)

                output_path = zip_path

            else:
                # Create MP4 video using ffmpeg
                output_path = os.path.join(www_path, f"{output_basename}.mp4")

                # Create temporary file list for ffmpeg
                list_file = os.path.join(www_path, f"input_list_{timestamp}.txt")
                await self.hass.async_add_executor_job(
                    self._write_ffmpeg_list_file_sync, list_file, filtered_images, interval
                )

                self.generation_status = "encoding_video"
                self.generation_progress = 25
                await self.event_manager.emit("TimelapseGenerationProgress", {
                    "device_name": camera_entity_id,
                    "progress": self.generation_progress,
                    "status": self.generation_status,
                    "file_count": len(filtered_images),
                }, haEvent=True)

                # Detect hardware acceleration and optimal encoder
                encoder, pix_fmt, hw_params = await self.hass.async_add_executor_job(
                    self.detect_hardware_acceleration
                )

                # Detect target resolution from images (preserve 4K if available)
                target_width, target_height = 1920, 1080  # Default to 1080p
                if filtered_images and "width" in filtered_images[0]:
                    img_width = filtered_images[0].get("width")
                    img_height = filtered_images[0].get("height")
                    if img_width and img_height:
                        target_width = img_width
                        target_height = img_height
                        _LOGGER.info(
                            f"{self.device_name}: Detected image resolution: {img_width}x{img_height}, "
                            "preserving in video"
                        )

                # Calculate dynamic fps for proper timelapse speed
                num_images = len(filtered_images)
                if num_images <= 10:
                    fps = 2
                elif num_images <= 20:
                    fps = 3
                elif num_images <= 30:
                    fps = 4
                else:
                    fps = 6

                _LOGGER.info(
                    f"{self.device_name}: Calculating fps for timelapse: {num_images} images @ {fps} fps = "
                    f"~{num_images / fps:.1f}s video, encoder: {encoder}, resolution: "
                    f"{target_width}x{target_height}"
                )

                # WATERMARK PREPARATION
                logo_png_path = self._resolve_logo_png_path()
                watermark_enabled = bool(logo_png_path)
                if watermark_enabled:
                    _LOGGER.info(
                        f"{self.device_name}: Watermark logo found: {logo_png_path}"
                    )
                else:
                    _LOGGER.warning(
                        f"{self.device_name}: ogb_tree.png not found, rendering without logo watermark"
                    )

                # Build ffmpeg command
                cmd = [
                    "ffmpeg",
                    "-y",  # Overwrite output file
                    "-f", "concat",
                    "-safe", "0",
                    "-i", list_file,
                ]

                # Add watermark as second input if available
                if watermark_enabled and logo_png_path:
                    cmd.extend(["-loop", "1", "-i", logo_png_path])

                # Build filter parameters
                title_text = (
                    f"OpenGrowBox Plant View - {plant_name}"
                    if plant_name else "OpenGrowBox Plant View"
                )
                subtitle_text = "Happy 420 with OpenGrowBox"

                if watermark_enabled and logo_png_path:
                    cmd.extend([
                        "-filter_complex",
                        (
                            f"[0:v]fps={fps},format={pix_fmt},"
                            f"scale={target_width}:{target_height}:flags=lanczos[base];"
                            f"[1:v]scale=70:70,format=rgba,colorchannelmixer=aa=0.5[wm];"
                            f"[base][wm]overlay=W-w-15:H-h-15:shortest=1[vout]"
                        ),
                        "-map", "[vout]",
                    ])
                else:
                    cmd.extend([
                        "-vf",
                        f"fps={fps},format={pix_fmt},"
                        f"scale={target_width}:{target_height}:flags=lanczos",
                    ])

                # Add encoding parameters
                cmd.extend([
                    "-c:v", encoder,
                    "-preset", "fast",
                    "-crf", "20",
                ])

                # Add hardware-specific parameters
                if hw_params:
                    cmd.extend(hw_params)

                # Add descriptive metadata to output
                cmd.extend([
                    "-metadata", f"title={title_text}",
                    "-metadata", f"plant_name={plant_name or ''}",
                    "-metadata", f"comment={subtitle_text}",
                    "-metadata", f"description={subtitle_text}",
                ])

                # Add output file
                cmd.append(output_path)

                _LOGGER.info(
                    f"{self.device_name}: Running ffmpeg with "
                    f"{'hardware' if hw_params else 'software'} encoding"
                )
                _LOGGER.debug(f"{self.device_name}: ffmpeg command: {' '.join(cmd)}")

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # HYBRID PROGRESS TRACKING
                last_size = 0
                estimated_max_size = None
                progress_update_count = 0
                MAX_PROGRESS_UPDATES = 60
                stuck_count = 0
                MAX_STUCK_COUNT = 10

                try:
                    while True:
                        if process.returncode is not None:
                            break

                        try:
                            current_size = await self.hass.async_add_executor_job(
                                os.path.getsize, output_path
                            )

                            if current_size > 0:
                                if estimated_max_size is None:
                                    estimated_duration = len(filtered_images) / fps
                                    estimated_max_size = max(
                                        2 * 1024 * 1024,
                                        (estimated_duration / 60) * 3 * 1024 * 1024
                                    )
                                    _LOGGER.debug(
                                        f"{self.device_name}: First data seen, estimating max size: "
                                        f"{estimated_max_size / (1024*1024):.2f}MB "
                                        f"(duration: {estimated_duration:.1f}s, fps: {fps})"
                                    )

                                if current_size > last_size:
                                    last_size = current_size
                                    stuck_count = 0

                                    progress = min(
                                        90, int((current_size / estimated_max_size) * 100)
                                    )

                                    if (
                                        progress > self.generation_progress + 5
                                        or progress_update_count % 10 == 0
                                    ):
                                        self.generation_progress = progress
                                        await self.event_manager.emit(
                                            "TimelapseGenerationProgress",
                                            {
                                                "device_name": camera_entity_id,
                                                "progress": progress,
                                                "status": "encoding_video",
                                            },
                                            haEvent=True,
                                        )
                                        progress_update_count += 1
                                else:
                                    stuck_count += 1
                                    if stuck_count >= MAX_STUCK_COUNT:
                                        _LOGGER.info(
                                            f"{self.device_name}: File size stuck for "
                                            f"{MAX_STUCK_COUNT * 0.5}s, assuming complete"
                                        )
                                        break

                            if process.returncode is not None:
                                break

                            progress_update_count += 1
                            if progress_update_count >= MAX_PROGRESS_UPDATES:
                                _LOGGER.warning(
                                    f"{self.device_name}: Max progress updates reached, assuming complete"
                                )
                                break

                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            _LOGGER.warning(
                                f"{self.device_name}: Error checking progress: {e}"
                            )

                        if process.returncode is None and self.generation_progress < 95:
                            self.generation_progress += 2
                            await self.event_manager.emit("TimelapseGenerationProgress", {
                                "device_name": camera_entity_id,
                                "progress": self.generation_progress,
                                "status": "encoding_video",
                            }, haEvent=True)

                        await asyncio.sleep(0.5)

                except Exception as e:
                    _LOGGER.error(f"{self.device_name}: Progress monitoring failed: {e}")

                # Wait for process to finish
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=300
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.communicate()
                    raise Exception("ffmpeg timed out during MP4 generation")

                # Clean up list file
                try:
                    await self.hass.async_add_executor_job(
                        self.storage._remove_file_sync, list_file
                    )
                    _LOGGER.debug(
                        f"{self.device_name}: Cleaned up temporary list file: {list_file}"
                    )
                except OSError as e:
                    _LOGGER.warning(
                        f"{self.device_name}: Failed to remove temporary file {list_file}: {e}"
                    )

                if process.returncode != 0:
                    raise Exception(f"ffmpeg failed: {stderr.decode()}")

                # Basic integrity guard
                if os.path.exists(output_path):
                    final_mp4_size = await self.hass.async_add_executor_job(
                        os.path.getsize, output_path
                    )
                    if final_mp4_size < 2048:
                        raise Exception("ffmpeg produced invalid MP4 (file too small)")

            # Success - return URL-based download metadata
            self.generation_status = "complete"
            self.generation_progress = 100

            def _get_file_size():
                try:
                    return os.path.getsize(output_path)
                except Exception as e:
                    _LOGGER.error(f"{self.device_name}: Failed to get file size: {e}")
                    return None

            file_size = await self.hass.async_add_executor_job(_get_file_size)

            if file_size is None:
                await self.event_manager.emit("TimelapseGenerationComplete", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "Failed to get generated file size",
                }, haEvent=True)
                return

            max_file_size = self._get_max_file_size()
            if file_size > max_file_size:
                _LOGGER.error(
                    f"{self.device_name}: Generated file exceeds "
                    f"{max_file_size / (1024*1024):.0f}MB limit: "
                    f"{file_size / (1024*1024):.2f}MB"
                )
                await self.event_manager.emit("TimelapseGenerationComplete", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": (
                        f"Generated file exceeds {max_file_size / (1024*1024):.0f}MB limit "
                        f"({file_size / (1024*1024):.2f}MB)"
                    ),
                }, haEvent=True)
                return

            download_url = (
                f"/local/ogb_data/{self.in_room}_img/timelapse_output/"
                f"{os.path.basename(output_path)}"
            )
            await self.event_manager.emit("TimelapseGenerationComplete", {
                "device_name": camera_entity_id,
                "success": True,
                "filename": os.path.basename(output_path),
                "format": output_format,
                "frame_count": len(filtered_images),
                "download_url": download_url,
                "file_size": file_size,
                "download_method": "url",
                "estimated_time": f"{len(filtered_images) / fps:.1f}s" if fps else None,
                "estimated_space": f"{file_size / (1024*1024):.1f} MB" if file_size else None,
            }, haEvent=True)

            _LOGGER.info(
                f"{self.device_name}: Timelapse generation complete: {output_path} "
                f"({file_size / (1024*1024):.2f}MB, URL download)"
            )

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Timelapse generation failed: {e}")
            self.generation_status = "error"

            await self.event_manager.emit("TimelapseGenerationComplete", {
                "device_name": camera_entity_id,
                "success": False,
                "error": f"Timelapse generation failed: {str(e)}",
            }, haEvent=True)

        finally:
            self.generation_active = False

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def handle_generate_timelapse(
        self,
        event,
        camera_entity_id: str,
        is_device_for_event: bool,
        get_plants_view_callback,
        get_current_plant_name_callback,
    ) -> None:
        """Handle opengrowbox_generate_timelapse event from frontend.

        Args:
            event: HA event with data containing start_date, end_date, format
            camera_entity_id: Camera entity ID for events
            is_device_for_event: Whether this device should handle the event
            get_plants_view_callback: Callback to get plantsView dict
            get_current_plant_name_callback: Callback to get current plant name
        """
        try:
            event_data = event.data
            device_name = event_data.get("device_name")

            if not is_device_for_event:
                return

            # Rate limiting check
            async with self._generation_lock:
                now = dt_util.now()
                if self._last_generation_time:
                    time_since_last = (now - self._last_generation_time).total_seconds()
                    if time_since_last < self._generation_cooldown:
                        _LOGGER.warning(
                            f"{self.device_name}: Generation request too soon "
                            f"({time_since_last:.1f}s), ignoring"
                        )
                        await self.event_manager.emit("TimelapseGenerationStarted", {
                            "device_name": camera_entity_id,
                            "error": "Rate limited - too soon",
                            "success": False,
                        }, haEvent=True)
                        return

                # Check if generation already active
                if self.generation_active:
                    _LOGGER.warning(
                        f"{self.device_name}: Timelapse generation already in progress"
                    )
                    await self.event_manager.emit("TimelapseGenerationStarted", {
                        "device_name": camera_entity_id,
                        "error": "Generation already in progress",
                        "success": False,
                    }, haEvent=True)
                    return

                self._last_generation_time = now

            # Get parameters
            start_date = event_data.get("start_date")
            end_date = event_data.get("end_date")
            output_format = event_data.get("format", "mp4")

            # Read interval from plantsView
            plants_view = get_plants_view_callback() or {}
            interval = int(plants_view.get("TimeLapseIntervall", "900") or "900")

            # Start generation in background task
            self.generation_task = asyncio.create_task(
                self.generate_timelapse_video(
                    start_date,
                    end_date,
                    interval,
                    output_format,
                    get_plants_view_callback,
                    get_current_plant_name_callback,
                    camera_entity_id,
                )
            )

            # Emit started event
            await self.event_manager.emit("TimelapseGenerationStarted", {
                "device_name": camera_entity_id,
                "start_date": start_date,
                "end_date": end_date,
                "format": output_format,
            }, haEvent=True)

            _LOGGER.info(f"{self.device_name}: Timelapse generation started")

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling generate timelapse: {e}")

    async def cancel_generation(self) -> None:
        """Cancel any active video generation task."""
        if self.generation_task and not self.generation_task.done():
            self.generation_task.cancel()
            try:
                await self.generation_task
            except asyncio.CancelledError:
                _LOGGER.info(
                    f"{self.device_name}: Timelapse generation task cancelled"
                )
            self.generation_task = None
