"""
Camera storage module.

Handles all blocking I/O operations for camera image management.
All file system operations are wrapped in executor to prevent blocking
the Home Assistant event loop.
"""

import os
import json
import base64
import zipfile
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

from homeassistant.util import dt as dt_util

from .utils import parse_datetime_value, sanitize_filename_part

_LOGGER = logging.getLogger(__name__)


class CameraStorage:
    """Handles all camera file I/O operations with executor wrapping."""

    def __init__(
        self,
        hass,
        device_name: str,
        in_room: str,
        event_manager,
        data_store,
    ):
        """Initialize camera storage.

        Args:
            hass: Home Assistant instance
            device_name: Camera device name
            in_room: Room identifier
            event_manager: Event manager for emitting events
            data_store: Data store for accessing configuration
        """
        self.hass = hass
        self.device_name = device_name
        self.in_room = in_room
        self.event_manager = event_manager
        self.data_store = data_store
        self.camera_storage_path: Optional[str] = None

    # =========================================================================
    # Path Management
    # =========================================================================

    def get_base_path(self) -> str:
        """Get the base storage path for this camera."""
        if self.camera_storage_path:
            return self.camera_storage_path
        return f"/config/ogb_data/{self.in_room}_img/{self.device_name}"

    def get_daily_path(self) -> str:
        """Get the daily photos directory path."""
        return os.path.join(self.get_base_path(), "daily")

    def get_timelapse_path(self) -> str:
        """Get the timelapse photos directory path."""
        return os.path.join(self.get_base_path(), "timelapse")

    def get_output_path(self) -> str:
        """Get the www output directory path for generated files."""
        if self.hass:
            return self.hass.config.path(
                "www", "ogb_data", f"{self.in_room}_img", "timelapse_output"
            )
        return f"/config/www/ogb_data/{self.in_room}_img/timelapse_output"

    def get_daily_output_path(self) -> str:
        """Get the www output directory path for daily zip files."""
        if self.hass:
            return self.hass.config.path(
                "www", "ogb_data", f"{self.in_room}_img", "daily_output"
            )
        return f"/config/www/ogb_data/{self.in_room}_img/daily_output"

    async def initialize_storage_paths(self) -> str:
        """Create storage directories and return the base path.

        Creates:
            - Base storage path
            - daily/ subdirectory
            - timelapse/ subdirectory

        Returns:
            The base storage path
        """
        if self.hass:
            base_path = self.hass.config.path("ogb_data")
        else:
            base_path = "/config/ogb_data"

        storage_path = os.path.join(base_path, f"{self.in_room}_img", self.device_name)

        try:
            os.makedirs(storage_path, exist_ok=True)
            _LOGGER.info(f"{self.device_name}: Created storage directory: {storage_path}")
        except Exception as mkdir_err:
            _LOGGER.warning(f"{self.device_name}: Could not create storage directory: {mkdir_err}")
            # Fallback to /tmp if not writable
            storage_path = f"/tmp/ogb_data/{self.in_room}_img/{self.device_name}"
            os.makedirs(storage_path, exist_ok=True)
            _LOGGER.info(f"{self.device_name}: Using fallback storage: {storage_path}")

        self.camera_storage_path = storage_path

        # Create daily/ subdirectory
        daily_path = os.path.join(storage_path, "daily")
        try:
            os.makedirs(daily_path, exist_ok=True)
            _LOGGER.info(f"{self.device_name}: Created daily snapshot directory: {daily_path}")
        except Exception as daily_mkdir_err:
            _LOGGER.warning(f"{self.device_name}: Could not create daily directory: {daily_mkdir_err}")

        # Create timelapse/ subdirectory
        timelapse_path = os.path.join(storage_path, "timelapse")
        try:
            os.makedirs(timelapse_path, exist_ok=True)
            _LOGGER.info(f"{self.device_name}: Created timelapse directory: {timelapse_path}")
        except Exception as tl_mkdir_err:
            _LOGGER.warning(f"{self.device_name}: Could not create timelapse directory: {tl_mkdir_err}")

        return storage_path

    def validate_storage_path(
        self, subdirectory: str = "daily", base_path: Optional[str] = None
    ) -> Tuple[str, str, str, str]:
        """Validate and return safe storage paths.

        Args:
            subdirectory: Subdirectory to validate (e.g., "daily", "timelapse")
            base_path: Optional base path override. Defaults to get_base_path().

        Returns:
            Tuple of (target_path, target_path_resolved, storage_path, storage_path_resolved)

        Raises:
            ValueError: If path traversal attempt detected
        """
        storage_path = base_path if base_path else self.get_base_path()
        target_path = os.path.join(storage_path, subdirectory)

        # Path validation: resolve to absolute path and check for traversal
        target_path_resolved = os.path.realpath(target_path)
        storage_path_resolved = os.path.realpath(storage_path)

        if not target_path_resolved.startswith(storage_path_resolved):
            raise ValueError(f"Path traversal attempt detected: {target_path}")

        return target_path, target_path_resolved, storage_path, storage_path_resolved

    def validate_file_path(self, file_path: str, allowed_directory: str) -> str:
        """Validate that a file path is within an allowed directory.

        Args:
            file_path: Path to validate
            allowed_directory: Directory that the path must be within

        Returns:
            The resolved file path

        Raises:
            ValueError: If path traversal attempt detected
        """
        file_path_resolved = os.path.realpath(file_path)
        allowed_directory_resolved = os.path.realpath(allowed_directory)

        if not file_path_resolved.startswith(allowed_directory_resolved):
            raise ValueError(f"Path traversal attempt detected: {file_path}")

        return file_path_resolved

    # =========================================================================
    # Image Save Operations
    # =========================================================================

    def _sync_save_image(self, path: str, image_data) -> None:
        """Synchronous image save - called via executor.

        Args:
            path: Full file path to save to
            image_data: Base64 encoded string or binary data
        """
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Handle different image formats
        if isinstance(image_data, str):
            # Base64 encoded image
            binary_data = base64.b64decode(image_data)
            with open(path, "wb") as f:
                f.write(binary_data)
        else:
            # Binary image data
            with open(path, "wb") as f:
                f.write(image_data)

    async def save_image(self, path: str, image_data) -> None:
        """Save image data to specified path (async wrapper).

        Args:
            path: Full file path to save to
            image_data: Base64 encoded string or binary data
        """
        try:
            if image_data:
                # Run sync file operation in executor to avoid blocking
                await self.hass.async_add_executor_job(
                    self._sync_save_image, path, image_data
                )
                _LOGGER.debug(f"{self.device_name}: Image saved to {path}")
            else:
                _LOGGER.warning(f"{self.device_name}: No image data to save")

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Failed to save image to {path}: {e}")

    async def save_daily_photo(self, image_data: str) -> Dict[str, Any]:
        """Save daily snapshot photo with YYYY-MM-DD_HHMMSS.jpg filename format.

        Args:
            image_data: Base64-encoded image data to save

        Returns:
            Result dict with keys:
                - success (bool): True if saved or already exists
                - filename (str): Saved filename
                - path (str): Full path to saved file
                - date (str): Date prefix (YYYY-MM-DD)
                - reason (str): "saved", "already_exists", or error message
        """
        try:
            # Get and validate storage path
            try:
                (
                    daily_path,
                    daily_path_resolved,
                    storage_path,
                    storage_path_resolved,
                ) = self.validate_storage_path("daily")
            except ValueError as e:
                _LOGGER.error(f"{self.device_name}: Path validation failed: {e}")
                return {
                    "success": False,
                    "reason": f"Path validation failed: {e}",
                    "filename": None,
                    "path": None,
                    "date": None,
                }

            # Ensure daily directory exists
            try:
                os.makedirs(daily_path, exist_ok=True)
            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Failed to create daily directory: {e}")
                return {
                    "success": False,
                    "reason": f"Failed to create daily directory: {e}",
                    "filename": None,
                    "path": None,
                    "date": None,
                }

            # Generate filename with timestamp (YYYY-MM-DD_HHMMSS.jpg format)
            timestamp = dt_util.now().strftime("%Y-%m-%d_%H%M%S")
            filename = f"{timestamp}.jpg"
            full_path = os.path.join(daily_path, filename)

            # Additional path validation on final file path
            self.validate_file_path(full_path, daily_path_resolved)

            # Check if we already have a snapshot for today (to avoid duplicates)
            today_prefix = dt_util.now().strftime("%Y-%m-%d")

            def _check_existing():
                if not os.path.exists(daily_path):
                    return []
                return [
                    f for f in os.listdir(daily_path)
                    if f.startswith(today_prefix) and f.endswith(".jpg")
                ]

            existing_photos = await self.hass.async_add_executor_job(_check_existing)

            if existing_photos:
                _LOGGER.info(
                    f"{self.device_name}: Daily snapshot already exists for today ({today_prefix}), skipping save"
                )
                return {
                    "success": True,
                    "filename": existing_photos[0],
                    "path": os.path.join(daily_path, existing_photos[0]),
                    "date": today_prefix,
                    "reason": "already_exists",
                }

            # Decode base64 image data to bytes for file write
            def _write_image():
                binary_data = base64.b64decode(image_data)
                with open(full_path, "wb") as f:
                    f.write(binary_data)
                return full_path

            # Use executor for blocking file write
            saved_path = await self.hass.async_add_executor_job(_write_image)

            _LOGGER.info(f"{self.device_name}: Daily snapshot saved: {saved_path}")

            return {
                "success": True,
                "filename": filename,
                "path": saved_path,
                "date": today_prefix,
                "reason": "saved",
            }

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Failed to save daily photo: {e}")
            return {
                "success": False,
                "reason": str(e),
                "filename": None,
                "path": None,
                "date": None,
            }

    # =========================================================================
    # Directory Listing Operations
    # =========================================================================

    def list_photos_sync(
        self,
        directory_path: str,
        include_size: bool = False,
        include_resolution: bool = False,
    ) -> List[Dict[str, Any]]:
        """Synchronous helper to list photos in a directory.

        This function runs in a thread pool executor to avoid blocking the event loop.

        Args:
            directory_path: Path to the directory to scan
            include_size: Whether to include file size in results
            include_resolution: Whether to include image resolution (requires PIL)

        Returns:
            List of photo dicts with keys: filename, mtime, and optionally size/width/height
        """
        result = []
        if not os.path.exists(directory_path):
            return result

        for filename in os.listdir(directory_path):
            if not filename.endswith((".jpg", ".jpeg", ".png")):
                continue

            file_path = os.path.join(directory_path, filename)
            try:
                file_stat = os.stat(file_path)
                photo_entry = {
                    "filename": filename,
                    "mtime": file_stat.st_mtime,
                }
                if include_size:
                    photo_entry["size"] = file_stat.st_size

                if include_resolution:
                    try:
                        from PIL import Image as PILImage
                        with PILImage.open(file_path) as img:
                            photo_entry["width"], photo_entry["height"] = img.size
                    except Exception:
                        pass  # PIL not available or file corrupted

                result.append(photo_entry)
            except Exception:
                continue

        return result

    def scan_timelapse_directory_sync(
        self,
        timelapse_path: str,
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Synchronous helper to scan timelapse directory for images.

        This function runs in a thread pool executor to avoid blocking the event loop.

        Args:
            timelapse_path: Path to timelapse directory
            start_dt: Optional start datetime filter
            end_dt: Optional end datetime filter

        Returns:
            List of image dicts with path, mtime, filename, width, height
        """
        all_images = []
        for root, dirs, files in os.walk(timelapse_path):
            for file in files:
                if file.endswith((".jpg", ".jpeg", ".png")):
                    file_path = os.path.join(root, file)
                    file_stat = os.stat(file_path)

                    # Create timezone-aware datetime in UTC to match start_dt/end_dt
                    file_mtime = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc)

                    # Check if within date range
                    if start_dt and file_mtime < start_dt:
                        continue
                    if end_dt and file_mtime > end_dt:
                        continue

                    # Detect image resolution using PIL (if available) for quality preservation
                    width, height = None, None
                    try:
                        from PIL import Image as PILImage
                        with PILImage.open(file_path) as img:
                            width, height = img.size
                    except ImportError:
                        pass  # PIL not available, keep resolution as None
                    except Exception as e:
                        _LOGGER.debug(f"{self.device_name}: Failed to read image resolution: {e}")

                    all_images.append({
                        "path": file_path,
                        "mtime": file_mtime,
                        "filename": file,
                        "width": width,
                        "height": height,
                    })
        return all_images

    # =========================================================================
    # ZIP Operations
    # =========================================================================

    def _create_zip_batch_sync(
        self,
        zip_path: str,
        images_batch: List[Dict[str, Any]],
    ) -> None:
        """Synchronous helper to add a batch of images to ZIP file.

        This function runs in a thread pool executor to avoid blocking the event loop.

        Args:
            zip_path: Path to ZIP file
            images_batch: List of image dicts with 'path' and 'filename' keys
        """
        with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zipf:
            for img in images_batch:
                # Use original filename to preserve timestamp information
                arcname = img["filename"]
                zipf.write(img["path"], arcname)

    def _create_zip_to_disk_sync(
        self,
        zip_path: str,
        photos: List[Tuple[str, str]],
    ) -> int:
        """Create ZIP file on disk with all photos.

        Args:
            zip_path: Path to create ZIP file
            photos: List of (filename, file_path) tuples

        Returns:
            Final ZIP file size in bytes
        """
        # Use ZIP_STORED for JPG (no recompression) - faster and no quality loss
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zipf:
            for i, (filename, file_path) in enumerate(photos):
                # Read and write in chunks to manage memory
                with open(file_path, "rb") as f:
                    file_data = f.read()
                zipf.writestr(filename, file_data)

                # Log progress every 50 files
                if (i + 1) % 50 == 0:
                    _LOGGER.debug(f"{self.device_name}: Processed {i + 1}/{len(photos)} photos")

        # Get final file size
        return os.path.getsize(zip_path)

    # =========================================================================
    # File Cleanup Operations
    # =========================================================================

    def _remove_file_sync(self, file_path: str) -> None:
        """Synchronous helper to remove a temporary file."""
        os.remove(file_path)

    def _create_output_directory_sync(self, www_path: str) -> None:
        """Synchronous helper to create output directory.

        This function runs in a thread pool executor to avoid blocking the event loop.
        """
        os.makedirs(www_path, exist_ok=True)

    async def delete_file(self, file_path: str) -> bool:
        """Delete a single file via executor.

        Args:
            file_path: Path to file to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            await self.hass.async_add_executor_job(self._remove_file_sync, file_path)
            return True
        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Failed to delete file {file_path}: {e}")
            return False

    async def delete_all_photos_in_directory(
        self,
        directory_path: str,
        extensions: Tuple[str, ...] = (".jpg", ".jpeg", ".png"),
    ) -> int:
        """Delete all photos in a directory.

        Args:
            directory_path: Path to directory
            extensions: File extensions to delete

        Returns:
            Number of files deleted
        """
        directory_path_resolved = os.path.realpath(directory_path)

        def _delete_all():
            deleted_count = 0
            try:
                for filename in os.listdir(directory_path):
                    if filename.lower().endswith(extensions):
                        file_path = os.path.join(directory_path, filename)

                        # Additional path validation on each file path
                        file_path_resolved = os.path.realpath(file_path)
                        if not file_path_resolved.startswith(directory_path_resolved):
                            _LOGGER.warning(
                                f"{self.device_name}: Path traversal attempt detected for {filename}"
                            )
                            continue

                        os.remove(file_path)
                        deleted_count += 1

                return deleted_count
            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Error deleting photos: {e}")
                raise

        return await self.hass.async_add_executor_job(_delete_all)

    # =========================================================================
    # State Hydration
    # =========================================================================

    async def hydrate_plants_view_from_disk(self, set_plants_view_callback) -> None:
        """Load plantsView from persisted room state and merge into datastore.

        Args:
            set_plants_view_callback: Callback function to set plantsView in datastore
        """
        try:
            if not self.hass:
                return

            state_path = self.hass.config.path(
                "ogb_data", f"ogb_{self.in_room.lower()}_state.json"
            )
            if not os.path.exists(state_path):
                return

            def _read_plants_view_sync():
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pv = data.get("plantsView") if isinstance(data, dict) else None
                return pv if isinstance(pv, dict) else None

            disk_plants_view = await self.hass.async_add_executor_job(_read_plants_view_sync)
            if not disk_plants_view:
                return

            # Use callback to merge into datastore
            set_plants_view_callback(disk_plants_view)
            _LOGGER.info(f"{self.device_name}: Hydrated plantsView from persisted state file")

        except Exception as e:
            _LOGGER.warning(f"{self.device_name}: Failed to hydrate plantsView from disk: {e}")

    # =========================================================================
    # Daily Photos Event Handlers
    # =========================================================================

    async def handle_get_daily_photos(
        self,
        device_name: str,
        camera_entity_id: str,
        is_device_for_event: bool,
    ) -> None:
        """Handle opengrowbox_get_daily_photos event.

        Args:
            device_name: Device name from event
            camera_entity_id: Camera entity ID for response
            is_device_for_event: Whether this device should handle the event
        """
        if not is_device_for_event:
            return

        try:
            daily_path = self.get_daily_path()

            # List daily photos (run in executor to avoid blocking)
            daily_photos = []
            try:
                if self.hass and os.path.exists(daily_path):
                    def _list_daily_photos():
                        result = []
                        if not os.path.exists(daily_path):
                            return result

                        for filename in os.listdir(daily_path):
                            if filename.endswith((".jpg", ".jpeg", ".png")):
                                # Extract date from filename (format: YYYY-MM-DD_HHMMSS.jpg)
                                date_part = filename.split("_")[0] if "_" in filename else filename
                                file_path = os.path.join(daily_path, filename)

                                # Get file modification time for accurate sorting
                                try:
                                    file_stat = os.stat(file_path)
                                    mtime = file_stat.st_mtime
                                except Exception:
                                    mtime = 0

                                result.append({
                                    "date": date_part,
                                    "filename": filename,
                                    "mtime": mtime,
                                })
                        return result

                    daily_photos = await self.hass.async_add_executor_job(_list_daily_photos)

                    # Sort by modification time (newest first)
                    daily_photos.sort(key=lambda x: x["mtime"], reverse=True)

                    # Remove mtime from response (internal use only)
                    for photo in daily_photos:
                        del photo["mtime"]

            except Exception as e:
                _LOGGER.warning(f"{self.device_name}: Error listing daily photos: {e}")

            # Emit response event
            await self.event_manager.emit("DailyPhotosResponse", {
                "camera_entity": camera_entity_id,
                "photos": daily_photos,
                "storage_path": daily_path,
                "count": len(daily_photos),
            }, haEvent=True)

            _LOGGER.info(f"{self.device_name}: Sent daily photos list (count: {len(daily_photos)})")

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling get daily photos: {e}")

    async def handle_delete_all_daily(
        self,
        device_name: str,
        camera_entity_id: str,
        is_device_for_event: bool,
    ) -> None:
        """Handle opengrowbox_delete_all_daily event.

        Args:
            device_name: Device name from event
            camera_entity_id: Camera entity ID for response
            is_device_for_event: Whether this device should handle the event
        """
        if not is_device_for_event:
            return

        try:
            # Validate storage path
            try:
                (
                    daily_path,
                    daily_path_resolved,
                    _,
                    _,
                ) = self.validate_storage_path("daily")
            except ValueError as e:
                _LOGGER.error(f"{self.device_name}: {e}")
                await self.event_manager.emit("DailyAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "Invalid storage path",
                }, haEvent=True)
                return

            # Check if daily folder exists
            if not os.path.exists(daily_path):
                _LOGGER.warning(f"{self.device_name}: Daily folder does not exist: {daily_path}")
                await self.event_manager.emit("DailyAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": True,
                    "deleted_count": 0,
                    "message": "Daily folder does not exist",
                }, haEvent=True)
                return

            # Delete all photo files
            try:
                deleted_count = await self.delete_all_photos_in_directory(daily_path)

                # Emit all photos deleted event
                await self.event_manager.emit("ogb_camera_all_daily_deleted", {
                    "device": self.device_name,
                    "room": self.in_room,
                    "camera_entity": camera_entity_id,
                    "deleted_count": deleted_count,
                    "timestamp": dt_util.now().isoformat(),
                }, haEvent=True)

                # Emit success response
                await self.event_manager.emit("DailyAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": True,
                    "deleted_count": deleted_count,
                }, haEvent=True)

                _LOGGER.info(f"{self.device_name}: Deleted all daily photos ({deleted_count} files)")

            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Failed to delete all daily photos: {e}")
                await self.event_manager.emit("DailyAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": str(e),
                }, haEvent=True)

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling delete all daily photos: {e}")
            await self.event_manager.emit("DailyAllDeletedResponse", {
                "device_name": camera_entity_id,
                "success": False,
                "error": str(e),
            }, haEvent=True)

    async def handle_download_daily_zip(
        self,
        device_name: str,
        camera_entity_id: str,
        start_date: Optional[str],
        end_date: Optional[str],
        is_device_for_event: bool,
    ) -> None:
        """Handle opengrowbox_download_daily_zip event.

        Args:
            device_name: Device name from event
            camera_entity_id: Camera entity ID for response
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
            is_device_for_event: Whether this device should handle the event
        """
        try:
            # Validate date formats if provided
            if start_date:
                try:
                    datetime.strptime(start_date, "%Y-%m-%d")
                except ValueError:
                    _LOGGER.error(f"{self.device_name}: Invalid start_date format: {start_date}")
                    await self.event_manager.emit("DailyZipResponse", {
                        "device_name": camera_entity_id,
                        "success": False,
                        "error": "Invalid start_date format (expected YYYY-MM-DD)",
                    }, haEvent=True)
                    return

            if end_date:
                try:
                    datetime.strptime(end_date, "%Y-%m-%d")
                except ValueError:
                    _LOGGER.error(f"{self.device_name}: Invalid end_date format: {end_date}")
                    await self.event_manager.emit("DailyZipResponse", {
                        "device_name": camera_entity_id,
                        "success": False,
                        "error": "Invalid end_date format (expected YYYY-MM-DD)",
                    }, haEvent=True)
                    return

            # Validate storage path
            try:
                (
                    daily_path,
                    daily_path_resolved,
                    _,
                    _,
                ) = self.validate_storage_path("daily")
            except ValueError as e:
                _LOGGER.error(f"{self.device_name}: {e}")
                await self.event_manager.emit("DailyZipResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "Invalid storage path",
                }, haEvent=True)
                return

            # Check if daily folder exists
            if not os.path.exists(daily_path):
                _LOGGER.warning(f"{self.device_name}: Daily folder does not exist: {daily_path}")
                await self.event_manager.emit("DailyZipResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "Daily folder does not exist",
                }, haEvent=True)
                return

            # Collect and filter photos by date range
            def _collect_photos():
                photos = []
                if not os.path.exists(daily_path):
                    return photos

                for filename in os.listdir(daily_path):
                    if filename.endswith((".jpg", ".jpeg", ".png")):
                        # Extract date from filename (format: YYYY-MM-DD_HHMMSS.jpg)
                        date_part = filename.split("_")[0] if "_" in filename else filename

                        # Filter by date range if provided
                        if start_date and date_part < start_date:
                            continue
                        if end_date and date_part > end_date:
                            continue

                        file_path = os.path.join(daily_path, filename)

                        # Path validation on each file
                        try:
                            self.validate_file_path(file_path, daily_path_resolved)
                        except ValueError:
                            _LOGGER.warning(
                                f"{self.device_name}: Path traversal attempt detected for {filename}"
                            )
                            continue

                        photos.append((filename, file_path))

                return photos

            try:
                photos = await self.hass.async_add_executor_job(_collect_photos)
            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Error collecting photos: {e}")
                await self.event_manager.emit("DailyZipResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": f"Failed to collect photos: {str(e)}",
                }, haEvent=True)
                return

            if not photos:
                _LOGGER.warning(f"{self.device_name}: No photos found for the specified date range")
                await self.event_manager.emit("DailyZipResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "No photos found for the specified date range",
                }, haEvent=True)
                return

            # Calculate total size before creating ZIP
            def _calculate_total_size():
                total_size = 0
                max_zip_size = 500 * 1024 * 1024  # 500MB limit
                for filename, file_path in photos:
                    try:
                        file_size = os.path.getsize(file_path)
                        total_size += file_size
                        if total_size > max_zip_size:
                            raise MemoryError(
                                f"Total size exceeds {max_zip_size / (1024*1024):.0f}MB limit"
                            )
                    except OSError as e:
                        _LOGGER.warning(
                            f"{self.device_name}: Could not get size for {filename}: {e}"
                        )
                        return None
                return total_size

            try:
                total_size = await self.hass.async_add_executor_job(_calculate_total_size)
                if total_size is None:
                    raise Exception("Failed to calculate total ZIP size")

                _LOGGER.info(
                    f"{self.device_name}: Creating daily ZIP with {len(photos)} photos "
                    f"(estimated size: {total_size / (1024*1024):.2f}MB)"
                )

                # Create output directory
                output_dir = self.get_daily_output_path()
                os.makedirs(output_dir, exist_ok=True)

                timestamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
                zip_filename = f"daily_photos_{timestamp}.zip"
                zip_path = os.path.join(output_dir, zip_filename)

                _LOGGER.info(f"{self.device_name}: Creating daily ZIP at {zip_path}")

                final_size = await self.hass.async_add_executor_job(
                    self._create_zip_to_disk_sync, zip_path, photos
                )

                download_url = f"/local/ogb_data/{self.in_room}_img/daily_output/{zip_filename}"
                await self.event_manager.emit("DailyZipResponse", {
                    "camera_entity": camera_entity_id,
                    "success": True,
                    "download_url": download_url,
                    "photo_count": len(photos),
                    "start_date": start_date,
                    "end_date": end_date,
                    "timestamp": dt_util.now().isoformat(),
                    "total_size": final_size,
                    "download_method": "url",
                }, haEvent=True)

                _LOGGER.info(
                    f"{self.device_name}: Generated daily ZIP with {len(photos)} photos "
                    f"(range: {start_date or 'all'} to {end_date or 'all'}, "
                    f"size: {final_size / (1024*1024):.2f}MB, URL download)"
                )

            except MemoryError as e:
                _LOGGER.error(
                    f"{self.device_name}: Memory limit exceeded for ZIP creation: {e}"
                )
                await self.event_manager.emit("DailyZipResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "Total file size exceeds 500MB limit. Please use smaller date ranges.",
                }, haEvent=True)

            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Failed to create ZIP: {e}")
                await self.event_manager.emit("DailyZipResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": f"Failed to create ZIP: {str(e)}",
                }, haEvent=True)

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling download daily ZIP: {e}")
            await self.event_manager.emit("DailyZipResponse", {
                "device_name": camera_entity_id,
                "success": False,
                "error": str(e),
            }, haEvent=True)

    async def handle_delete_all_timelapse(
        self,
        device_name: str,
        camera_entity_id: str,
        is_device_for_event: bool,
    ) -> None:
        """Handle opengrowbox_delete_all_timelapse event.

        Args:
            device_name: Device name from event
            camera_entity_id: Camera entity ID for response
            is_device_for_event: Whether this device should handle the event
        """
        if not is_device_for_event:
            return

        try:
            # Validate storage path
            try:
                (
                    timelapse_path,
                    timelapse_path_resolved,
                    _,
                    _,
                ) = self.validate_storage_path("timelapse")
            except ValueError as e:
                _LOGGER.error(f"{self.device_name}: {e}")
                await self.event_manager.emit("TimelapseAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "Invalid storage path",
                }, haEvent=True)
                return

            # Check if timelapse folder exists
            if not os.path.exists(timelapse_path):
                _LOGGER.warning(
                    f"{self.device_name}: Timelapse folder does not exist: {timelapse_path}"
                )
                await self.event_manager.emit("TimelapseAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": True,
                    "deleted_count": 0,
                    "message": "Timelapse folder does not exist",
                }, haEvent=True)
                return

            # Delete all timelapse photo files
            try:
                deleted_count = await self.delete_all_photos_in_directory(timelapse_path)

                # Emit all timelapse photos deleted event
                await self.event_manager.emit("ogb_camera_all_timelapse_deleted", {
                    "device": self.device_name,
                    "room": self.in_room,
                    "camera_entity": camera_entity_id,
                    "deleted_count": deleted_count,
                    "timestamp": dt_util.now().isoformat(),
                }, haEvent=True)

                # Emit success response
                await self.event_manager.emit("TimelapseAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": True,
                    "deleted_count": deleted_count,
                }, haEvent=True)

                _LOGGER.info(
                    f"{self.device_name}: Deleted all timelapse photos ({deleted_count} files)"
                )

            except Exception as e:
                _LOGGER.error(
                    f"{self.device_name}: Failed to delete all timelapse photos: {e}"
                )
                await self.event_manager.emit("TimelapseAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": str(e),
                }, haEvent=True)

        except Exception as e:
            _LOGGER.error(
                f"{self.device_name}: Error handling delete all timelapse photos: {e}"
            )
            await self.event_manager.emit("TimelapseAllDeletedResponse", {
                "device_name": camera_entity_id,
                "success": False,
                "error": str(e),
            }, haEvent=True)

    async def handle_delete_all_timelapse_output(
        self,
        device_name: str,
        camera_entity_id: str,
        is_device_for_event: bool,
    ) -> None:
        """Handle opengrowbox_delete_all_timelapse_output event.

        Deletes all timelapse output files (MP4/ZIP) from the www output directory.

        Args:
            device_name: Device name from event
            camera_entity_id: Camera entity ID for response
            is_device_for_event: Whether this device should handle the event
        """
        if not is_device_for_event:
            return

        try:
            # Get base path for www/ogb_data
            www_base_path = (
                self.hass.config.path("www", "ogb_data") if self.hass
                else "/config/www/ogb_data"
            )
            www_path = self.get_output_path()

            # Path validation - use empty subdirectory since get_output_path() already returns full path
            try:
                (
                    _,
                    www_path_resolved,
                    _,
                    _,
                ) = self.validate_storage_path(
                    subdirectory=f"{self.in_room}_img/timelapse_output",
                    base_path=www_base_path
                )
            except ValueError as e:
                _LOGGER.error(f"{self.device_name}: {e}")
                await self.event_manager.emit("TimelapseOutputAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": "Invalid storage path",
                }, haEvent=True)
                return

            # Check if timelapse output folder exists
            if not os.path.exists(www_path):
                _LOGGER.warning(
                    f"{self.device_name}: Timelapse output folder does not exist: {www_path}"
                )
                await self.event_manager.emit("TimelapseOutputAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": True,
                    "deleted_count": 0,
                    "message": "Timelapse output folder does not exist",
                }, haEvent=True)
                return

            # Delete all timelapse output files (MP4 and ZIP)
            try:
                deleted_count = await self.delete_all_photos_in_directory(
                    www_path, extensions=(".mp4", ".zip")
                )

                # Emit all timelapse output deleted event
                await self.event_manager.emit("ogb_camera_all_timelapse_output_deleted", {
                    "device": self.device_name,
                    "room": self.in_room,
                    "camera_entity": camera_entity_id,
                    "deleted_count": deleted_count,
                    "timestamp": dt_util.now().isoformat(),
                }, haEvent=True)

                # Emit success response
                await self.event_manager.emit("TimelapseOutputAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": True,
                    "deleted_count": deleted_count,
                }, haEvent=True)

                _LOGGER.info(
                    f"{self.device_name}: Deleted all timelapse output files ({deleted_count} files)"
                )

            except Exception as e:
                _LOGGER.error(
                    f"{self.device_name}: Failed to delete all timelapse output files: {e}"
                )
                await self.event_manager.emit("TimelapseOutputAllDeletedResponse", {
                    "device_name": camera_entity_id,
                    "success": False,
                    "error": str(e),
                }, haEvent=True)

        except Exception as e:
            _LOGGER.error(
                f"{self.device_name}: Error handling delete all timelapse output: {e}"
            )
            await self.event_manager.emit("TimelapseOutputAllDeletedResponse", {
                "device_name": camera_entity_id,
                "success": False,
                "error": str(e),
            }, haEvent=True)
