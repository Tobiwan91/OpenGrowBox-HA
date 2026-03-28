"""
Camera scheduling module.

Handles timelapse and daily snapshot scheduling with Home Assistant timers.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone, time
from typing import Optional, Callable, Awaitable, Dict, Any

from homeassistant.util import dt as dt_util
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval

from .utils import parse_datetime_value, to_storage_iso

_LOGGER = logging.getLogger(__name__)


class CameraScheduler:
    """Handles timelapse and daily snapshot scheduling."""

    def __init__(
        self,
        hass,
        device_name: str,
        in_room: str,
        event_manager,
        data_store,
        storage,
        get_plants_view: Callable[[], Optional[Dict[str, Any]]],
        set_plants_view: Callable[[Dict[str, Any]], None],
        capture_callback: Callable[[str], Awaitable[Optional[str]]],
        emit_recording_status: Callable[..., Awaitable[None]],
    ):
        """Initialize camera scheduler.

        Args:
            hass: Home Assistant instance
            device_name: Camera device name
            in_room: Room identifier
            event_manager: Event manager for emitting events
            data_store: Data store for accessing configuration
            storage: CameraStorage instance
            get_plants_view: Callback to get plantsView dict
            set_plants_view: Callback to set plantsView dict
            capture_callback: Async callback to capture image (returns base64 data)
            emit_recording_status: Callback to emit recording status events
        """
        self.hass = hass
        self.device_name = device_name
        self.in_room = in_room
        self.event_manager = event_manager
        self.data_store = data_store
        self.storage = storage
        self._get_plants_view = get_plants_view
        self._set_plants_view = set_plants_view
        self._capture_callback = capture_callback
        self._emit_recording_status = emit_recording_status

        # Timelapse state
        self.tl_active = False
        self.tl_start_time: Optional[datetime] = None
        self.tl_end_time: Optional[datetime] = None
        self.tl_image_count = 0

        # Timer unsubscribe callbacks
        self._timelapse_unsub = None
        self._timelapse_start_unsub = None
        self._daily_snapshot_unsub = None

    @property
    def camera_entity_id(self) -> str:
        """Get the camera entity ID."""
        return f"camera.{self.device_name}"

    # =========================================================================
    # Timelapse Control
    # =========================================================================

    async def start_timelapse(
        self,
        start_dt: datetime,
        end_dt: datetime,
        resume: bool = False,
    ) -> bool:
        """Start timelapse capture.

        Args:
            start_dt: When to start capturing
            end_dt: When to stop capturing
            resume: If True, don't reset image count

        Returns:
            True if started successfully
        """
        self._stop_timelapse_timers()

        now = dt_util.now()

        # Update state
        self.tl_start_time = start_dt
        self.tl_end_time = end_dt

        # Update plantsView
        plants_view = self._get_plants_view() or {}
        plants_view["isTimeLapseActive"] = True

        if not resume:
            # Count existing photos in timelapse directory instead of resetting to 0
            # This preserves the cumulative count across all recordings
            timelapse_path = self.storage.get_timelapse_path()
            existing_photos = self.storage.list_photos_sync(timelapse_path, False, False)
            self.tl_image_count = len(existing_photos)
            plants_view["tl_image_count"] = self.tl_image_count

        self._set_plants_view(plants_view)

        # Start capturing immediately or schedule for later
        if start_dt <= now:
            await self._start_interval_capture(start_dt, end_dt)
        else:
            await self._schedule_timelapse_start(start_dt, end_dt)

        return True

    async def stop_timelapse(self, user_initiated: bool = False) -> None:
        """Stop timelapse capture.

        Args:
            user_initiated: If True, this was stopped by user action
        """
        self._stop_timelapse_timers()
        was_active = self.tl_active
        self.tl_active = False

        # Calculate duration
        duration = 0
        if self.tl_start_time:
            duration = (dt_util.now() - self.tl_start_time).total_seconds()

        # Update plantsView
        plants_view = self._get_plants_view() or {}
        plants_view["isTimeLapseActive"] = False
        self._set_plants_view(plants_view)

        # Emit status update
        if was_active:
            await self._emit_recording_status(is_recording=False)

        # Emit completion event
        await self.event_manager.emit(
            "TimelapseCompleted",
            {
                "device": self.device_name,
                "device_name": f"camera.{self.device_name}",
                "total_images": self.tl_image_count,
                "duration": duration,
                "user_initiated": user_initiated,
            },
            haEvent=True,
        )

        await self.event_manager.emit(
            "SaveState",
            {
                "source": "Camera",
                "device": self.device_name,
                "action": "stop_recording",
            },
        )

    async def _start_interval_capture(self, start_dt: datetime, end_dt: datetime) -> None:
        """Start the interval-based capture scheduler.

        Args:
            start_dt: When timelapse started
            end_dt: When timelapse should end
        """
        plants_view = self._get_plants_view() or {}
        interval_sec = int(plants_view.get("TimeLapseIntervall", "900") or "900")
        interval_sec = max(30, interval_sec)

        self._stop_timelapse_timers()

        self.tl_start_time = start_dt
        self.tl_end_time = end_dt
        self.tl_active = True

        is_plant_day = self.data_store.getDeep("isPlantDay.islightON")
        camera_entity_id = f"camera.{self.device_name}"

        # Capture first image immediately (if allowed)
        capture_at_night = plants_view.get("capture_at_night", False)
        if is_plant_day or capture_at_night:
            await self._capture_and_save_timelapse_image()
        else:
            _LOGGER.debug(
                f"{self.device_name}: Skipped initial capture - lights off, "
                "night capture disabled"
            )

        # Start interval scheduler
        self._timelapse_unsub = async_track_time_interval(
            self.hass, self._timelapse_interval_callback, timedelta(seconds=interval_sec)
        )

        _LOGGER.info(
            f"{self.device_name}: Timelapse capture started "
            f"(interval: {interval_sec}s, end: {dt_util.as_local(end_dt).isoformat()})"
        )

        await self._emit_recording_status(is_recording=True)

    async def _schedule_timelapse_start(self, start_dt: datetime, end_dt: datetime) -> None:
        """Schedule a delayed start for timelapse.

        Args:
            start_dt: When to start capturing
            end_dt: When timelapse should end
        """
        self._stop_timelapse_timers()

        self.tl_start_time = start_dt
        self.tl_end_time = end_dt
        self.tl_active = True

        def start_callback(now):
            loop = self.hass.loop
            asyncio.run_coroutine_threadsafe(
                self._start_interval_capture(start_dt, end_dt), loop
            )

        self._timelapse_start_unsub = async_track_point_in_time(
            self.hass, start_callback, start_dt
        )

        _LOGGER.info(
            f"{self.device_name}: Timelapse scheduled to start at "
            f"{dt_util.as_local(start_dt).isoformat()}"
        )

        await self._emit_recording_status(is_recording=False, is_scheduled=True)

    async def _timelapse_interval_callback(self, now: datetime) -> None:
        """Callback triggered by HA scheduler for timelapse photos."""
        try:
            now_utc = now.astimezone(timezone.utc)

            # Check if timelapse has ended
            if self.tl_end_time and now_utc > self.tl_end_time:
                _LOGGER.info(f"{self.device_name}: Timelapse duration exceeded")
                await self.stop_timelapse(user_initiated=False)
                return

            # Check night mode
            is_plant_day = self.data_store.getDeep("isPlantDay.islightON")
            plants_view = self._get_plants_view() or {}
            capture_at_night = plants_view.get("capture_at_night", False)

            if not is_plant_day and not capture_at_night:
                _LOGGER.debug(
                    f"{self.device_name}: Skipping capture - lights off, "
                    "night capture disabled"
                )
                await self._emit_recording_status(is_recording=True, is_night_mode=True)
                return

            # Capture and save image
            await self._capture_and_save_timelapse_image()

            # Save state
            asyncio.create_task(
                self.event_manager.emit(
                    "SaveState", {"source": "Camera", "device": self.device_name}
                )
            )

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Timelapse callback error: {e}")

    async def _capture_and_save_timelapse_image(self) -> bool:
        """Capture and save a timelapse image.

        Returns:
            True if captured successfully
        """
        camera_entity_id = f"camera.{self.device_name}"
        image_data = await self._capture_callback(camera_entity_id)

        if image_data:
            import os
            image_path = self.storage.get_timelapse_path()
            now_local = dt_util.as_local(dt_util.now())
            timestamp_str = now_local.strftime("%Y%m%d_%H%M%S")
            filename = f"{self.device_name}_{timestamp_str}.jpg"
            full_path = os.path.join(image_path, filename)

            await self.storage.save_image(full_path, image_data)
            self.tl_image_count += 1

            # Update plantsView
            plants_view = self._get_plants_view() or {}
            plants_view["tl_image_count"] = self.tl_image_count
            self._set_plants_view(plants_view)

            await self._emit_recording_status(is_recording=True)
            return True
        else:
            await self._emit_recording_status(is_recording=True, capture_failed=True)
            return False

    def _stop_timelapse_timers(self) -> None:
        """Cancel all timelapse-related timers."""
        if self._timelapse_unsub is not None:
            self._timelapse_unsub()
            self._timelapse_unsub = None

        if self._timelapse_start_unsub is not None:
            self._timelapse_start_unsub()
            self._timelapse_start_unsub = None

    # =========================================================================
    # Daily Snapshot Scheduling
    # =========================================================================

    async def schedule_daily_snapshot(self) -> None:
        """Schedule daily snapshot using async_track_point_in_time()."""
        try:
            plants_view = self._get_plants_view() or {}
            enabled = plants_view.get("daily_snapshot_enabled", False)
            config_time = plants_view.get("daily_snapshot_time", "09:00")

            # Cancel previous schedule
            if self._daily_snapshot_unsub is not None:
                self._daily_snapshot_unsub()
                self._daily_snapshot_unsub = None
                _LOGGER.debug(
                    f"{self.device_name}: Cancelled previous daily snapshot schedule"
                )

            if not enabled:
                _LOGGER.debug(
                    f"{self.device_name}: Daily snapshots disabled, not scheduling"
                )
                return

            # Parse target time
            try:
                target_time = time.fromisoformat(config_time)
            except ValueError as e:
                _LOGGER.error(
                    f"{self.device_name}: Invalid daily_snapshot_time format "
                    f"'{config_time}': {e}"
                )
                return

            # Calculate next capture time
            now = dt_util.now()
            next_capture = now.replace(
                hour=target_time.hour,
                minute=target_time.minute,
                second=0,
                microsecond=0,
            )

            if next_capture <= now:
                next_capture += timedelta(days=1)

            self._daily_snapshot_unsub = async_track_point_in_time(
                self.hass, self._daily_snapshot_callback, next_capture
            )

            _LOGGER.debug(
                f"{self.device_name}: Scheduled daily snapshot for "
                f"{next_capture.isoformat()} (target: {config_time})"
            )

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Failed to schedule daily snapshot: {e}")

    async def _daily_snapshot_callback(self, *args) -> None:
        """Callback triggered when scheduled daily snapshot time arrives."""
        try:
            _LOGGER.info(f"{self.device_name}: Daily snapshot triggered")

            # Ensure directory exists
            import os
            daily_path = self.storage.get_daily_path()
            try:
                os.makedirs(daily_path, exist_ok=True)
            except Exception as e:
                _LOGGER.error(
                    f"{self.device_name}: Failed to create daily directory: {e}"
                )
                await self.event_manager.emit(
                    "ogb_camera_capture_failed",
                    {
                        "device": self.device_name,
                        "room": self.in_room,
                        "error": f"Failed to create daily directory: {e}",
                        "retry_count": 0,
                        "capture_type": "daily",
                    },
                    haEvent=True,
                )
                await self.schedule_daily_snapshot()
                return

            # Capture image
            camera_entity_id = f"camera.{self.device_name}"
            image_data = await self._capture_callback(camera_entity_id)

            if image_data:
                # Save daily photo
                result = await self.storage.save_daily_photo(image_data)

                if result["success"]:
                    if result["reason"] == "already_exists":
                        await self.event_manager.emit(
                            "ogb_camera_daily_photo_exists",
                            {
                                "device": self.device_name,
                                "room": self.in_room,
                                "date": result["date"],
                                "existing_file": result["filename"],
                            },
                            haEvent=True,
                        )
                    else:
                        await self.event_manager.emit(
                            "ogb_camera_daily_photo_captured",
                            {
                                "device": self.device_name,
                                "room": self.in_room,
                                "camera_entity": camera_entity_id,
                                "date": result["date"],
                                "filename": result["filename"],
                                "path": result["path"],
                                "timestamp": dt_util.now().isoformat(),
                            },
                            haEvent=True,
                        )
                else:
                    _LOGGER.warning(
                        f"{self.device_name}: Failed to save daily photo: "
                        f"{result['reason']}"
                    )
                    await self.event_manager.emit(
                        "ogb_camera_capture_failed",
                        {
                            "device": self.device_name,
                            "room": self.in_room,
                            "error": result["reason"],
                            "retry_count": 0,
                            "capture_type": "daily",
                        },
                        haEvent=True,
                    )
            else:
                _LOGGER.warning(
                    f"{self.device_name}: Failed to capture daily snapshot after retries"
                )

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Daily snapshot callback error: {e}")
            await self.event_manager.emit(
                "ogb_camera_capture_failed",
                {
                    "device": self.device_name,
                    "room": self.in_room,
                    "error": str(e),
                    "retry_count": 0,
                    "capture_type": "daily",
                },
                haEvent=True,
            )

        finally:
            # Reschedule for next day
            await self.schedule_daily_snapshot()

    def cancel_daily_snapshot(self) -> None:
        """Cancel daily snapshot schedule."""
        if self._daily_snapshot_unsub is not None:
            self._daily_snapshot_unsub()
            self._daily_snapshot_unsub = None
            _LOGGER.info(f"{self.device_name}: Daily snapshots cancelled")

    # =========================================================================
    # Timelapse Restore
    # =========================================================================

    async def restore_timelapse_after_restart(self) -> None:
        """Restore active or scheduled timelapse after integration restart."""
        try:
            plants_view = self._get_plants_view() or {}

            if not plants_view.get("isTimeLapseActive", False):
                return

            start_str = plants_view.get("StartDate", "")
            end_str = plants_view.get("EndDate", "")

            start_dt = parse_datetime_value(start_str)
            end_dt = parse_datetime_value(end_str)

            # Restore image count
            self.tl_image_count = int(plants_view.get("tl_image_count", 0) or 0)

            if not start_dt or not end_dt:
                _LOGGER.warning(
                    f"{self.device_name}: Invalid StartDate/EndDate during restore. "
                    "Applying safe fallback."
                )
                now = dt_util.now()
                start_dt = now
                end_dt = now + timedelta(days=30)

                plants_view["StartDate"] = to_storage_iso(start_dt)
                plants_view["EndDate"] = to_storage_iso(end_dt)
                self._set_plants_view(plants_view)
                asyncio.create_task(
                    self.event_manager.emit(
                        "SaveState",
                        {
                            "source": "Camera",
                            "device": self.device_name,
                            "action": "restore_repaired_dates",
                        },
                    )
                )

            now = dt_util.now()
            self.tl_start_time = start_dt
            self.tl_end_time = end_dt

            if end_dt <= now:
                _LOGGER.info(
                    f"{self.device_name}: Timelapse end time passed, not restoring"
                )
                plants_view["isTimeLapseActive"] = False
                self._set_plants_view(plants_view)
                await self._emit_recording_status(is_recording=False)
                await self.event_manager.emit(
                    "SaveState",
                    {
                        "source": "Camera",
                        "device": self.device_name,
                        "action": "restore_expired",
                    },
                )
                return

            if start_dt <= now:
                _LOGGER.info(
                    f"{self.device_name}: Restoring active timelapse after restart"
                )
                await self._start_interval_capture(start_dt, end_dt)
            else:
                _LOGGER.info(
                    f"{self.device_name}: Restoring scheduled timelapse after restart"
                )
                await self._schedule_timelapse_start(start_dt, end_dt)

            await self.event_manager.emit(
                "SaveState",
                {"source": "Camera", "device": self.device_name, "action": "restore_recording"},
            )

        except Exception as e:
            _LOGGER.error(
                f"{self.device_name}: Failed to restore timelapse: {e}"
            )

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def cleanup(self) -> None:
        """Cleanup all scheduled tasks."""
        self._stop_timelapse_timers()
        self.cancel_daily_snapshot()

        if self.tl_active:
            self.tl_active = False
            _LOGGER.info(f"{self.device_name}: Stopped timelapse during cleanup")
