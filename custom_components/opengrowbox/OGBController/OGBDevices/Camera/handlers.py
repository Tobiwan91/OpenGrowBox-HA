"""
Camera event handlers module.

Handles all Home Assistant bus event routing and processing for camera devices.
"""

import base64
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from homeassistant.util import dt as dt_util

from .utils import parse_datetime_value, to_storage_iso

_LOGGER = logging.getLogger(__name__)


class CameraEventHandlers:
    """Routes and handles Home Assistant bus events for camera devices."""

    def __init__(
        self,
        hass,
        device_name: str,
        in_room: str,
        event_manager,
        data_store,
        storage,
        video_gen,
        scheduler,
        capture,
        get_plants_view: Callable[[], Optional[Dict[str, Any]]],
        set_plants_view: Callable[[Dict[str, Any]], None],
        get_current_plant_name: Callable[[], Optional[str]],
        is_device_for_event: Callable[[str], bool],
        emit_recording_status: Callable,
    ):
        """Initialize camera event handlers.

        Args:
            hass: Home Assistant instance
            device_name: Camera device name
            in_room: Room identifier
            event_manager: Event manager for emitting events
            data_store: Data store for configuration
            storage: CameraStorage instance
            video_gen: VideoGenerator instance
            scheduler: CameraScheduler instance
            capture: CameraCapture instance
            get_plants_view: Callback to get plantsView dict
            set_plants_view: Callback to set plantsView dict
            get_current_plant_name: Callback to get current plant name
            is_device_for_event: Callback to check if event is for this device
            emit_recording_status: Callback to emit recording status events
        """
        self.hass = hass
        self.device_name = device_name
        self.in_room = in_room
        self.event_manager = event_manager
        self.data_store = data_store
        self.storage = storage
        self.video_gen = video_gen
        self.scheduler = scheduler
        self.capture = capture
        self._get_plants_view = get_plants_view
        self._set_plants_view = set_plants_view
        self._get_current_plant_name = get_current_plant_name
        self._is_device_for_event = is_device_for_event
        self._emit_recording_status = emit_recording_status

        self.camera_entity_id = f"camera.{device_name}"

        # Lazy-loaded notificator for HA notifications
        self._notificator = None

    def register_all(self) -> None:
        """Register all Home Assistant event listeners."""
        # Timelapse events
        self.hass.bus.async_listen(
            "opengrowbox_get_timelapse_config", self._handle_get_timelapse_config
        )
        self.hass.bus.async_listen(
            "opengrowbox_save_timelapse_config", self._handle_save_timelapse_config
        )
        self.hass.bus.async_listen(
            "opengrowbox_generate_timelapse", self._handle_generate_timelapse
        )
        self.hass.bus.async_listen(
            "opengrowbox_get_timelapse_status", self._handle_get_timelapse_status
        )
        self.hass.bus.async_listen(
            "opengrowbox_start_timelapse", self._handle_start_timelapse
        )
        self.hass.bus.async_listen(
            "opengrowbox_stop_timelapse", self._handle_stop_timelapse
        )

        # Daily photo events
        self.hass.bus.async_listen(
            "opengrowbox_get_daily_photos", self._handle_get_daily_photos
        )
        self.hass.bus.async_listen(
            "opengrowbox_get_daily_photo", self._handle_get_daily_photo
        )
        self.hass.bus.async_listen(
            "opengrowbox_delete_daily_photo", self._handle_delete_daily_photo
        )
        self.hass.bus.async_listen(
            "opengrowbox_delete_all_daily", self._handle_delete_all_daily
        )
        self.hass.bus.async_listen(
            "opengrowbox_download_daily_zip", self._handle_download_daily_zip
        )

        # Timelapse deletion events
        self.hass.bus.async_listen(
            "opengrowbox_delete_all_timelapse", self._handle_delete_all_timelapse
        )
        self.hass.bus.async_listen(
            "opengrowbox_delete_all_timelapse_output",
            self._handle_delete_all_timelapse_output,
        )

        # Timelapse photos listing
        self.hass.bus.async_listen(
            "opengrowbox_get_timelapse_photos", self._handle_get_timelapse_photos
        )

        # User plant view request
        self.hass.bus.async_listen(
            "opengrowbox_user_needs_image", self._handle_user_needs_image
        )

        _LOGGER.info(f"{self.device_name}: Registered all event handlers")

    # =========================================================================
    # Event Emission Helpers
    # =========================================================================

    async def _emit_response(
        self,
        event_type: str,
        data: Dict[str, Any],
        success: bool = True,
    ) -> None:
        """Emit a standardized response event.

        Args:
            event_type: Event type to emit
            data: Event data (device_name will be added automatically)
            success: Whether the operation was successful
        """
        data["device_name"] = self.camera_entity_id
        if "success" not in data:
            data["success"] = success
        await self.event_manager.emit(event_type, data, haEvent=True)

    # =========================================================================
    # Timelapse Event Handlers
    # =========================================================================

    async def _handle_get_timelapse_config(self, event) -> None:
        """Handle opengrowbox_get_timelapse_config event."""
        try:
            device_name = event.data.get("device_name")
            if not self._is_device_for_event(device_name):
                return

            plants_view = self._get_plants_view() or {}
            timelapse_path = self.storage.get_timelapse_path()

            # List available timelapses
            available_timelapses = []
            try:
                if self.hass and os.path.exists(timelapse_path):

                    def _list_timelapses():
                        image_count = len([
                            f for f in os.listdir(timelapse_path)
                            if f.endswith((".jpg", ".jpeg", ".png"))
                        ])
                        if image_count > 0:
                            return [{
                                "folder": "timelapse",
                                "path": timelapse_path,
                                "image_count": image_count,
                            }]
                        return []

                    available_timelapses = await self.hass.async_add_executor_job(
                        _list_timelapses
                    )
            except Exception as e:
                _LOGGER.warning(
                    f"{self.device_name}: Error listing timelapse folders: {e}"
                )

            is_recording_active = (
                plants_view.get("isTimeLapseActive", False) or self.scheduler.tl_active
            )

            config_response = {
                "device_name": self.camera_entity_id,
                "storage_path": timelapse_path,
                "current_config": {
                    "interval": plants_view.get("TimeLapseIntervall", "900"),
                    "duration": plants_view.get("duration", 3600),
                    "image_path": timelapse_path,
                    "StartDate": plants_view.get("StartDate", ""),
                    "EndDate": plants_view.get("EndDate", ""),
                    "OutPutFormat": plants_view.get("OutPutFormat", "mp4"),
                    "daily_snapshot_enabled": plants_view.get(
                        "daily_snapshot_enabled", False
                    ),
                    "daily_snapshot_time": plants_view.get("daily_snapshot_time", "09:00"),
                    "capture_at_night": plants_view.get("capture_at_night", False),
                },
                "available_timelapses": available_timelapses,
                "tl_active": is_recording_active,
                "tl_start_time": (
                    self.scheduler.tl_start_time.isoformat()
                    if self.scheduler.tl_start_time else None
                ),
                "tl_image_count": self.scheduler.tl_image_count,
                "last_capture_time": (
                    self.capture.last_capture_time.isoformat()
                    if self.capture.last_capture_time else None
                ),
            }

            await self.event_manager.emit(
                "TimelapseConfigResponse", config_response, haEvent=True
            )
            _LOGGER.info(f"{self.device_name}: Sent timelapse config")

        except Exception as e:
            _LOGGER.error(
                f"{self.device_name}: Error handling get timelapse config: {e}"
            )

    async def _handle_save_timelapse_config(self, event) -> None:
        """Handle opengrowbox_save_timelapse_config event."""
        try:
            device_name = event.data.get("device_name")
            if not self._is_device_for_event(device_name):
                return

            new_config = event.data.get("config", {})
            plants_view = self._get_plants_view() or {}

            # Update configuration fields
            if "isTimeLapseActive" in new_config:
                plants_view["isTimeLapseActive"] = new_config["isTimeLapseActive"]
            if "interval" in new_config:
                plants_view["TimeLapseIntervall"] = str(new_config["interval"])
            if "startDate" in new_config:
                parsed = parse_datetime_value(new_config["startDate"])
                plants_view["StartDate"] = to_storage_iso(parsed) if parsed else ""
            if "endDate" in new_config:
                parsed = parse_datetime_value(new_config["endDate"])
                plants_view["EndDate"] = to_storage_iso(parsed) if parsed else ""
            if "format" in new_config:
                plants_view["OutPutFormat"] = new_config["format"]
            if "daily_snapshot_enabled" in new_config:
                plants_view["daily_snapshot_enabled"] = new_config[
                    "daily_snapshot_enabled"
                ]
            if "daily_snapshot_time" in new_config:
                plants_view["daily_snapshot_time"] = new_config["daily_snapshot_time"]
            if "capture_at_night" in new_config:
                plants_view["capture_at_night"] = new_config["capture_at_night"]

            self._set_plants_view(plants_view)

            # Handle daily snapshot scheduling
            daily_enabled = plants_view.get("daily_snapshot_enabled", False)
            if daily_enabled:
                await self.scheduler.schedule_daily_snapshot()
                _LOGGER.info(
                    f"{self.device_name}: Daily snapshots rescheduled with time "
                    f"{plants_view.get('daily_snapshot_time', '09:00')}"
                )
            else:
                self.scheduler.cancel_daily_snapshot()

            await self._emit_response(
                "TimelapseConfigSaved",
                {"config": plants_view},
            )

            await self.event_manager.emit(
                "SaveState", {"source": "Camera", "device": self.device_name}
            )

        except Exception as e:
            _LOGGER.error(
                f"{self.device_name}: Error handling save timelapse config: {e}"
            )
            await self._emit_response(
                "TimelapseConfigSaved",
                {"error": str(e)},
                success=False,
            )

    async def _handle_generate_timelapse(self, event) -> None:
        """Handle opengrowbox_generate_timelapse event."""
        await self.video_gen.handle_generate_timelapse(
            event,
            self.camera_entity_id,
            self._is_device_for_event(event.data.get("device_name")),
            self._get_plants_view,
            self._get_current_plant_name,
        )

    async def _handle_get_timelapse_status(self, event) -> None:
        """Handle opengrowbox_get_timelapse_status event."""
        try:
            device_name = event.data.get("device_name")
            if not self._is_device_for_event(device_name):
                return

            plants_view = self._get_plants_view() or {}
            persisted_active = bool(plants_view.get("isTimeLapseActive", False))
            effective_active = self.scheduler.tl_active or persisted_active

            # Check if timelapse is scheduled (waiting to start) vs actively recording
            is_scheduled = self.scheduler._timelapse_start_unsub is not None
            is_recording = effective_active and not is_scheduled

            # Reuse the main recording status emitter
            await self._emit_recording_status(
                is_recording=is_recording,
                is_scheduled=is_scheduled,
            )

            # Emit status response (unique to this handler - includes video generation info)
            await self.event_manager.emit(
                "TimelapseStatusResponse",
                {
                    "device_name": self.camera_entity_id,
                    "tl_active": effective_active,
                    "tl_start_time": (
                        self.scheduler.tl_start_time.isoformat()
                        if self.scheduler.tl_start_time else None
                    ),
                    "tl_image_count": self.scheduler.tl_image_count,
                    "generation_active": getattr(
                        self.video_gen, "generation_active", False
                    ),
                    "generation_progress": getattr(
                        self.video_gen, "generation_progress", 0
                    ),
                    "generation_status": getattr(
                        self.video_gen, "generation_status", "idle"
                    ),
                },
                haEvent=True,
            )

        except Exception as e:
            _LOGGER.error(
                f"{self.device_name}: Error handling get timelapse status: {e}"
            )

    async def _handle_start_timelapse(self, event) -> None:
        """Handle opengrowbox_start_timelapse event."""
        try:
            device_name = event.data.get("device_name")
            if not self._is_device_for_event(device_name):
                return

            plants_view = self._get_plants_view() or {}
            start_str = plants_view.get("StartDate", "")
            end_str = plants_view.get("EndDate", "")

            start_dt = parse_datetime_value(start_str)
            end_dt = parse_datetime_value(end_str)

            if not start_dt or not end_dt:
                _LOGGER.error(
                    f"{self.device_name}: Invalid StartDate or EndDate - cannot start"
                )
                await self.event_manager.emit(
                    "TimelapseError",
                    {
                        "device": self.device_name,
                        "reason": "invalid_datetime",
                        "message": "Start date and end date must be valid",
                    },
                    haEvent=True,
                )
                return

            await self.scheduler.start_timelapse(start_dt, end_dt, resume=False)

            _LOGGER.info(f"{self.device_name}: Timelapse started via event")

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling start timelapse: {e}")

    async def _handle_stop_timelapse(self, event) -> None:
        """Handle opengrowbox_stop_timelapse event."""
        try:
            device_name = event.data.get("device_name")
            if not self._is_device_for_event(device_name):
                return

            await self.scheduler.stop_timelapse(user_initiated=True)
            _LOGGER.info(f"{self.device_name}: Timelapse stopped via event")

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling stop timelapse: {e}")

    # =========================================================================
    # Daily Photo Event Handlers
    # =========================================================================

    async def _handle_get_daily_photos(self, event) -> None:
        """Handle opengrowbox_get_daily_photos event."""
        device_name = event.data.get("device_name")
        await self.storage.handle_get_daily_photos(
            device_name,
            self.camera_entity_id,
            self._is_device_for_event(device_name),
        )

    async def _handle_get_daily_photo(self, event) -> None:
        """Handle opengrowbox_get_daily_photo event."""
        try:
            device_name = event.data.get("device_name")
            date_str = event.data.get("date")

            if not self._is_device_for_event(device_name):
                return

            if not date_str:
                await self._emit_response(
                    "DailyPhotoResponse",
                    {"error": "No date provided"},
                    success=False,
                )
                return

            # Find photo by date
            daily_path = self.storage.get_daily_path()
            photo_filename = None
            photo_path = None

            try:
                daily_path_resolved = os.path.realpath(daily_path)

                def _find_photo():
                    if not os.path.exists(daily_path):
                        return None, None
                    for filename in os.listdir(daily_path):
                        if filename.endswith((".jpg", ".jpeg", ".png")):
                            if filename.startswith(date_str):
                                file_path = os.path.join(daily_path, filename)
                                file_path_resolved = os.path.realpath(file_path)
                                if not file_path_resolved.startswith(
                                    daily_path_resolved
                                ):
                                    continue
                                return filename, file_path
                    return None, None

                photo_filename, photo_path = await self.hass.async_add_executor_job(
                    _find_photo
                )

            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Error finding daily photo: {e}")

            if not photo_path or not os.path.exists(photo_path):
                await self._emit_response(
                    "DailyPhotoResponse",
                    {"error": f"No photo found for date {date_str}", "date": date_str},
                    success=False,
                )
                return

            # Read and encode photo
            def _read_photo():
                with open(photo_path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")

            try:
                image_base64 = await self.hass.async_add_executor_job(_read_photo)

                await self.event_manager.emit(
                    "DailyPhotoResponse",
                    {
                        "camera_entity": self.camera_entity_id,
                        "success": True,
                        "date": date_str,
                        "filename": photo_filename,
                        "image_data": image_base64,
                        "timestamp": dt_util.now().isoformat(),
                    },
                    haEvent=True,
                )

                _LOGGER.info(
                    f"{self.device_name}: Sent daily photo for {date_str} ({photo_filename})"
                )

            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Failed to read photo: {e}")
                await self._emit_response(
                    "DailyPhotoResponse",
                    {"error": f"Failed to read photo: {str(e)}", "date": date_str},
                    success=False,
                )

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling get daily photo: {e}")
            await self._emit_response(
                "DailyPhotoResponse",
                {"error": str(e)},
                success=False,
            )

    async def _handle_delete_daily_photo(self, event) -> None:
        """Handle opengrowbox_delete_daily_photo event."""
        try:
            device_name = event.data.get("device_name")
            date_str = event.data.get("date")

            if not self._is_device_for_event(device_name):
                return

            if not date_str:
                await self._emit_response(
                    "DailyPhotoDeletedResponse",
                    {"error": "No date provided"},
                    success=False,
                )
                return

            # Validate date format
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                await self._emit_response(
                    "DailyPhotoDeletedResponse",
                    {"error": "Invalid date format (expected YYYY-MM-DD)"},
                    success=False,
                )
                return

            # Find photo by date
            daily_path = self.storage.get_daily_path()
            photo_filename = None
            photo_path = None

            try:
                daily_path_resolved = os.path.realpath(daily_path)

                def _find_photo():
                    if not os.path.exists(daily_path):
                        return None, None
                    for filename in os.listdir(daily_path):
                        if filename.endswith((".jpg", ".jpeg", ".png")):
                            if filename.startswith(date_str):
                                file_path = os.path.join(daily_path, filename)
                                file_path_resolved = os.path.realpath(file_path)
                                if not file_path_resolved.startswith(
                                    daily_path_resolved
                                ):
                                    continue
                                return filename, file_path
                    return None, None

                photo_filename, photo_path = await self.hass.async_add_executor_job(
                    _find_photo
                )

            except Exception as e:
                _LOGGER.error(f"{self.device_name}: Error finding daily photo: {e}")

            if not photo_path or not os.path.exists(photo_path):
                await self._emit_response(
                    "DailyPhotoDeletedResponse",
                    {"error": f"No photo found for date {date_str}", "date": date_str},
                    success=False,
                )
                return

            # Delete photo
            await self.storage.delete_file(photo_path)

            await self.event_manager.emit(
                "ogb_camera_photo_deleted",
                {
                    "device": self.device_name,
                    "room": self.in_room,
                    "camera_entity": self.camera_entity_id,
                    "date": date_str,
                    "filename": photo_filename,
                    "timestamp": dt_util.now().isoformat(),
                },
                haEvent=True,
            )

            await self._emit_response(
                "DailyPhotoDeletedResponse",
                {"date": date_str, "filename": photo_filename},
            )

            _LOGGER.info(
                f"{self.device_name}: Deleted daily photo for {date_str} ({photo_filename})"
            )

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling delete daily photo: {e}")
            await self._emit_response(
                "DailyPhotoDeletedResponse",
                {"error": str(e)},
                success=False,
            )

    async def _handle_delete_all_daily(self, event) -> None:
        """Handle opengrowbox_delete_all_daily event."""
        device_name = event.data.get("device_name")
        await self.storage.handle_delete_all_daily(
            device_name,
            self.camera_entity_id,
            self._is_device_for_event(device_name),
        )

    async def _handle_download_daily_zip(self, event) -> None:
        """Handle opengrowbox_download_daily_zip event."""
        device_name = event.data.get("device_name")
        start_date = event.data.get("start_date")
        end_date = event.data.get("end_date")
        await self.storage.handle_download_daily_zip(
            device_name,
            self.camera_entity_id,
            start_date,
            end_date,
            self._is_device_for_event(device_name),
        )

    # =========================================================================
    # Timelapse Photo Management Handlers
    # =========================================================================

    async def _handle_delete_all_timelapse(self, event) -> None:
        """Handle opengrowbox_delete_all_timelapse event."""
        device_name = event.data.get("device_name")
        await self.storage.handle_delete_all_timelapse(
            device_name,
            self.camera_entity_id,
            self._is_device_for_event(device_name),
        )

    async def _handle_delete_all_timelapse_output(self, event) -> None:
        """Handle opengrowbox_delete_all_timelapse_output event."""
        device_name = event.data.get("device_name")
        await self.storage.handle_delete_all_timelapse_output(
            device_name,
            self.camera_entity_id,
            self._is_device_for_event(device_name),
        )

    async def _handle_get_timelapse_photos(self, event) -> None:
        """Handle opengrowbox_get_timelapse_photos event."""
        try:
            device_name = event.data.get("device_name")
            if not self._is_device_for_event(device_name):
                return

            timelapse_path = self.storage.get_timelapse_path()
            output_path = self.storage.get_output_path()

            # List timelapse photos
            timelapse_photos = []
            total_count = 0

            if not os.path.exists(timelapse_path):
                os.makedirs(timelapse_path, exist_ok=True)

            try:
                if self.hass:
                    timelapse_photos = await self.hass.async_add_executor_job(
                        self.storage.list_photos_sync, timelapse_path, True, False
                    )
                    total_count = len(timelapse_photos)
                    timelapse_photos.sort(key=lambda x: x["mtime"], reverse=True)
            except Exception as e:
                _LOGGER.warning(
                    f"{self.device_name}: Error listing timelapse photos: {e}"
                )

            # List output files
            def _list_output_files():
                results = []
                if not os.path.exists(output_path):
                    return results
                for filename in os.listdir(output_path):
                    if not filename.lower().endswith((".mp4", ".zip")):
                        continue
                    file_path = os.path.join(output_path, filename)
                    try:
                        stat = os.stat(file_path)
                        ext = os.path.splitext(filename)[1].lower().lstrip(".")
                        results.append({
                            "filename": filename,
                            "format": ext,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                            "download_url": (
                                f"/local/ogb_data/{self.in_room}_img/"
                                f"timelapse_output/{filename}"
                            ),
                        })
                    except Exception:
                        continue
                results.sort(key=lambda x: x["mtime"], reverse=True)
                return results

            output_files = []
            output_count = 0
            output_counts = {"mp4": 0, "zip": 0}

            try:
                if self.hass:
                    output_files = await self.hass.async_add_executor_job(
                        _list_output_files
                    )
                output_count = len(output_files)
                output_counts["mp4"] = len(
                    [f for f in output_files if f.get("format") == "mp4"]
                )
                output_counts["zip"] = len(
                    [f for f in output_files if f.get("format") == "zip"]
                )
                # # Remove mtime from response
                # for f in output_files:
                #     f.pop("mtime", None)
            except Exception as e:
                _LOGGER.warning(
                    f"{self.device_name}: Error listing timelapse outputs: {e}"
                )

            # Calculate date range
            date_range = None
            if timelapse_photos:
                oldest = min(p["mtime"] for p in timelapse_photos)
                newest = max(p["mtime"] for p in timelapse_photos)
                date_range = {
                    "oldest": datetime.fromtimestamp(oldest).isoformat(),
                    "newest": datetime.fromtimestamp(newest).isoformat(),
                }

            # Remove mtime from photos
            for photo in timelapse_photos:
                photo.pop("mtime", None)

            await self.event_manager.emit(
                "TimelapsePhotosResponse",
                {
                    "camera_entity": self.camera_entity_id,
                    "photos": timelapse_photos,
                    "total_count": total_count,
                    "active_image_count": self.scheduler.tl_image_count,
                    "storage_path": timelapse_path,
                    "date_range": date_range,
                    "output_files": output_files,
                    "output_count": output_count,
                    "output_counts": output_counts,
                },
                haEvent=True,
            )

            _LOGGER.info(
                f"{self.device_name}: Sent timelapse photos response "
                f"(count: {total_count}, active: {self.scheduler.tl_image_count})"
            )

        except Exception as e:
            _LOGGER.error(
                f"{self.device_name}: Error handling get timelapse photos: {e}"
            )

    # =========================================================================
    # User Image Request Handler
    # =========================================================================

    async def _handle_user_needs_image(self, event) -> None:
        """Handle opengrowbox_user_needs_image from API.

        Response goes via Premium Integration (encrypted).
        """
        try:
            # Event can come from HA bus (event.data) or internal emitter (plain dict)
            if hasattr(event, "data"):
                event_data = event.data or {}
            elif isinstance(event, dict):
                event_data = event
            else:
                event_data = {}

            device_name = event_data.get("device_name")
            request_socket_id = event_data.get("request_socket_id")
            request_room_id = event_data.get("room_id")
            force_new = bool(event_data.get("force_new", False))

            # Only respond if this event is for this camera
            if device_name and not self._is_device_for_event(device_name):
                _LOGGER.debug(
                    f"{self.device_name}: Event not for this camera (device: {device_name})"
                )
                await self.event_manager.emit(
                    "LogForClient",
                    {
                        "Name": self.in_room,
                        "Type": "Security",
                        "Message": (
                            f"Camera request mismatch: requested={device_name}, "
                            f"current={self.camera_entity_id}"
                        ),
                        "ControllerType": "API",
                        "DebugType": "WARNING",
                    },
                    haEvent=True,
                    debug_type="WARNING",
                )
                await self._send_mismatch_notification(device_name)
                return

            _LOGGER.info(
                f"{self.device_name}: Processing plant view request for room: {self.in_room}"
            )
            await self.event_manager.emit(
                "LogForClient",
                {
                    "Name": self.in_room,
                    "Type": "Camera",
                    "Message": f"NeedViewPlant received for {self.camera_entity_id}",
                    "ControllerType": "API",
                    "DebugType": "INFO",
                },
                haEvent=True,
                debug_type="INFO",
            )
            await self._send_request_notification(request_socket_id)

            # Check if we have a recent cached image (<5 minutes)
            if not force_new:
                image_data = self.capture.get_cached_image(max_age_minutes=5)
            else:
                image_data = None

            cache_status = "cached"
            capture_time = self.capture.last_capture_time

            if image_data:
                _LOGGER.info(
                    f"{self.device_name}: Using cached image (captured {capture_time})"
                )
            else:
                # Capture new image
                _LOGGER.info(
                    f"{self.device_name}: Capturing new image "
                    f"({'forced' if force_new else 'no cache or too old'})"
                )
                image_data = await self.capture.get_ha_camera_image(self.camera_entity_id)

                if image_data:
                    self.capture.last_image = image_data
                    self.capture.last_capture_time = dt_util.now()
                    cache_status = "new"
                    capture_time = self.capture.last_capture_time
                    _LOGGER.info(f"{self.device_name}: Captured new image successfully")
                else:
                    await self.event_manager.emit(
                        "user_image_response",
                        {
                            "device_name": self.camera_entity_id,
                            "success": False,
                            "error": "Failed to capture image from camera",
                        },
                    )
                    return

            # Build plant data
            plant_data = {
                "room": self.in_room,
                "mainControl": self.data_store.get("mainControl"),
                "tentMode": self.data_store.get("tentMode"),
                "strainName": self.data_store.get("strainName"),
                "plantStage": self.data_store.get("plantStage"),
                "planttype": self.data_store.get("plantType"),
                "cultivationArea": self.data_store.get("growAreaM2"),
                "vpd": self.data_store.get("vpd"),
                "isLightON": self.data_store.get("isPlantDay"),
                "plantDates": self.data_store.get("plantDates"),
                "tentData": self.data_store.get("tentData"),
                "Hydro": self.data_store.get("Hydro"),
                "growMediums": self.data_store.get("growMediums"),
                "controlOptions": self.data_store.get("controlOptions"),
                "capabilities": self.data_store.get("capabilities"),
                "actionData": self.data_store.get("actionData") or {},
            }

            await self.event_manager.emit(
                "HasPlantViewed",
                {
                    "device_name": self.camera_entity_id,
                    "image_data": image_data,
                    "cache_status": cache_status,
                    "capture_time": capture_time.isoformat() if capture_time else None,
                    "room": self.in_room,
                    "room_id": request_room_id,
                    "request_socket_id": request_socket_id,
                    "plant_data": plant_data,
                },
            )

            _LOGGER.info(
                f"{self.device_name}: HasPlantViewed emitted with image and plant data"
            )
            await self.event_manager.emit(
                "LogForClient",
                {
                    "Name": self.in_room,
                    "Type": "Camera",
                    "Message": (
                        f"Plant image captured ({cache_status}) and queued "
                        f"for encrypted API forwarding"
                    ),
                    "ControllerType": "API",
                    "DebugType": "INFO",
                },
                haEvent=True,
                debug_type="INFO",
            )
            await self._send_capture_notification(cache_status)

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error handling user_needs_image: {e}")
            await self.event_manager.emit(
                "LogForClient",
                {
                    "Name": self.in_room,
                    "Type": "Security",
                    "Message": f"user_needs_image failed: {e}",
                    "ControllerType": "API",
                    "DebugType": "ERROR",
                },
                haEvent=True,
                debug_type="ERROR",
            )
            await self.event_manager.emit(
                "user_image_response",
                {
                    "device_name": self.camera_entity_id,
                    "success": False,
                    "error": str(e),
                },
            )

    # =========================================================================
    # Notification Helper Methods
    # =========================================================================

    async def _get_notificator(self):
        """Lazy-load OGBNotificator instance."""
        if self._notificator is None:
            from ...managers.OGBNotifyManager import OGBNotificator
            self._notificator = OGBNotificator(self.hass, self.in_room)
        return self._notificator

    async def _send_mismatch_notification(self, requested_device: str):
        """Send warning notification for device mismatch."""
        try:
            notificator = await self._get_notificator()
            await notificator.warning(
                title=f"OGB {self.in_room}: Camera Request Mismatch",
                message=(
                    f"Image request target mismatch. Requested device: {requested_device}, "
                    f"handled camera: {self.camera_entity_id}."
                ),
            )
        except Exception as e:
            _LOGGER.debug(
                f"{self.device_name}: Could not send mismatch notification: {e}"
            )

    async def _send_request_notification(self, request_socket_id: str = None):
        """Send info notification when image is requested."""
        try:
            notificator = await self._get_notificator()
            await notificator.info(
                title=f"OGB {self.in_room}: Plant Image Requested",
                message=(
                    f"NeedViewPlant received for {self.camera_entity_id}. "
                    f"Request socket: {request_socket_id or 'n/a'}"
                ),
            )
        except Exception as e:
            _LOGGER.debug(
                f"{self.device_name}: Could not send request notification: {e}"
            )

    async def _send_capture_notification(self, cache_status: str):
        """Send info notification when image is captured."""
        try:
            if self._notificator is not None:
                await self._notificator.info(
                    title=f"OGB {self.in_room}: Plant Image Captured",
                    message=(
                        f"Image captured ({cache_status}) and queued for encrypted API forwarding "
                        f"from {self.camera_entity_id}."
                    ),
                )
        except Exception as e:
            _LOGGER.debug(
                f"{self.device_name}: Could not send capture notification: {e}"
            )
