"""
Camera device module for OpenGrowBox.

This module provides the Camera class which handles camera device management,
timelapse recording, daily snapshots, and video generation for grow room monitoring.

Architecture:
    - Camera (main class) - Lifecycle management, state coordination
    - CameraCapture - Image capture with retry logic
    - CameraScheduler - Timelapse and daily snapshot scheduling
    - CameraEventHandlers - HA bus event routing
    - CameraStorage - File I/O operations
    - VideoGenerator - FFmpeg video generation
    - utils - Pure utility functions
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List

from ..Device import Device

from .utils import parse_datetime_value, to_storage_iso
from .storage import CameraStorage
from .video_generator import VideoGenerator
from .capture import CameraCapture
from .scheduling import CameraScheduler
from .handlers import CameraEventHandlers

_LOGGER = logging.getLogger(__name__)


class Camera(Device):
    """Camera device for timelapse recording and daily snapshots.

    This class serves as the main coordinator for camera functionality,
    delegating specific responsibilities to specialized modules:
        - CameraCapture: Image capture with retry logic
        - CameraScheduler: Timelapse and daily snapshot scheduling
        - CameraEventHandlers: HA bus event routing
        - CameraStorage: File I/O operations
        - VideoGenerator: FFmpeg video generation

    The Camera class itself handles:
        - Device initialization and lifecycle
        - PlantsView state management
        - Module coordination and dependency injection
    """

    def __init__(
        self,
        deviceName,
        deviceData,
        eventManager,
        dataStore,
        deviceType,
        inRoom,
        hass,
        deviceLabel="EMPTY",
        allLabels=[],
    ):
        """Initialize camera device.

        Args:
            deviceName: Unique device identifier
            deviceData: Device configuration data
            eventManager: Event manager for inter-component communication
            dataStore: Data store for configuration persistence
            deviceType: Type of device (should be "camera")
            inRoom: Room identifier this camera belongs to
            hass: Home Assistant instance
            deviceLabel: Optional label for the device
            allLabels: List of all labels for the device
        """
        super().__init__(
            deviceName,
            deviceData,
            eventManager,
            dataStore,
            deviceType,
            inRoom,
            hass,
            deviceLabel,
            allLabels,
        )

        # Store device data for camera access
        self.deviceData = deviceData
        self.camera_entity_id = "camera." + self.deviceName

        # Init lifecycle guards
        self._init_started = False
        self._init_completed = False

        # Initialize helper modules
        self.storage = CameraStorage(
            hass, deviceName, inRoom, eventManager, dataStore
        )
        self.video_gen = VideoGenerator(
            hass, self.storage, eventManager, deviceName, inRoom
        )
        self.capture = CameraCapture(
            hass, deviceName, inRoom, eventManager
        )
        self.scheduler = CameraScheduler(
            hass=hass,
            device_name=deviceName,
            in_room=inRoom,
            event_manager=eventManager,
            data_store=dataStore,
            storage=self.storage,
            get_plants_view=self._get_plants_view,
            set_plants_view=self._set_plants_view,
            capture_callback=self._capture_image,
            emit_recording_status=self._emit_recording_status,
        )
        self.handlers = CameraEventHandlers(
            hass=hass,
            device_name=deviceName,
            in_room=inRoom,
            event_manager=eventManager,
            data_store=dataStore,
            storage=self.storage,
            video_gen=self.video_gen,
            scheduler=self.scheduler,
            capture=self.capture,
            get_plants_view=self._get_plants_view,
            set_plants_view=self._set_plants_view,
            get_current_plant_name=self._get_current_plant_name,
            is_device_for_event=self._is_device_for_event,
            emit_recording_status=self._emit_recording_status,
        )

        # Register internal event listeners
        self.eventManager.on("StartTL", self.startTL)
        self.eventManager.on("NeedViewPlant", self._handle_user_needs_image_internal)

        # Initialize camera once on startup
        if self.hass and hasattr(self.hass, "async_create_task"):
            self.hass.async_create_task(self.init())
        else:
            asyncio.create_task(self.init())

    # =========================================================================
    # PlantsView Helpers (State Management)
    # =========================================================================

    def _get_plants_view_key(self) -> str:
        """Get the shared plantsView key for this room."""
        return "plantsView"

    def _get_plants_view(self) -> Optional[Dict[str, Any]]:
        """Get shared plantsView from datastore."""
        return self.dataStore.get(self._get_plants_view_key()) or {}

    def _set_plants_view(self, plants_view: Dict[str, Any]) -> None:
        """Set shared plantsView in datastore."""
        self.dataStore.set(self._get_plants_view_key(), plants_view)

    def _get_current_plant_name(self) -> Optional[str]:
        """Resolve current plant name from growMediums in datastore."""
        try:
            grow_mediums = self.dataStore.get("growMediums")
            if not isinstance(grow_mediums, list):
                return None

            # Prefer explicit plant_name, fallback to medium name
            for medium in grow_mediums:
                if not isinstance(medium, dict):
                    continue
                plant_name = str(medium.get("plant_name") or "").strip()
                if plant_name:
                    return plant_name

            for medium in grow_mediums:
                if not isinstance(medium, dict):
                    continue
                medium_name = str(medium.get("name") or "").strip()
                if medium_name:
                    return medium_name
        except Exception as e:
            _LOGGER.debug(
                f"{self.deviceName}: Could not resolve plant name from growMediums: {e}"
            )

        return None

    # =========================================================================
    # Device Validation
    # =========================================================================

    def _is_device_for_event(self, device_name: str) -> bool:
        """Check if this camera should handle the given event.

        Args:
            device_name: The device_name from the event

        Returns:
            True if this camera should handle the event
        """
        if not device_name:
            return False

        normalized = str(device_name).strip().lower()
        return normalized in {
            self.deviceName.lower(),
            self.camera_entity_id.lower(),
            f"camera.{self.deviceName}".lower(),
        }

    # =========================================================================
    # Device Initialization
    # =========================================================================

    def deviceInit(self, entitys):
        """Minimal initialization for camera - stores entity in options.

        Called by Device base class during initialization.

        Args:
            entitys: Camera entity or list of entities
        """
        # Store camera entities
        self.camera_entities = entitys if isinstance(entitys, list) else [entitys]

        # Store camera entity in options (like other devices)
        if self.camera_entities:
            for entity in self.camera_entities:
                if isinstance(entity, dict) and entity.get("entity_id", "").startswith(
                    "camera."
                ):
                    self.options.append(entity)

        self.identifyCapabilities()

        # Set initialization flags directly
        self.initialization = True
        self.isInitialized = True

    async def init(self):
        """Initialize camera - calls parent first for capabilities.

        Creates storage directories, loads persisted state, and restores
        any active timelapse recordings.
        """
        if self._init_started:
            _LOGGER.debug(
                f"{self.deviceName}: init already started, skipping duplicate call"
            )
            return

        self._init_started = True
        #_LOGGER.debug(f"Device: {self.deviceName} Initialization started {self}")

        try:
            # Strong restore: read persisted plantsView directly from room state file
            await self.storage.hydrate_plants_view_from_disk(self._set_plants_view)

            # Wait for saved state to be loaded into dataStore
            for attempt in range(10):
                plants_view = self._get_plants_view()
                if plants_view and (
                    plants_view.get("tl_image_count", 0) > 0
                    or "daily_snapshot_enabled" in plants_view
                    or "capture_at_night" in plants_view
                    or plants_view.get("isTimeLapseActive", False)
                    or bool(plants_view.get("StartDate"))
                    or bool(plants_view.get("EndDate"))
                ):
                    _LOGGER.info(
                        f"{self.deviceName}: Saved state detected in dataStore "
                        f"(attempt {attempt + 1})"
                    )
                    break
                if attempt < 9:
                    await asyncio.sleep(0.5)
            else:
                _LOGGER.warning(
                    f"{self.deviceName}: Saved state may not be loaded yet, "
                    "proceeding with available data"
                )

            # Initialize storage paths
            storage_path = await self.storage.initialize_storage_paths()
            self.camera_storage_path = storage_path

            # Load plantsView from dataStore
            plants_view = self._get_plants_view()

            # Restore timelapse counter from persisted state
            if plants_view:
                self.scheduler.tl_image_count = int(
                    plants_view.get("tl_image_count", 0) or 0
                )

            # Register event handlers (after storage is initialized)
            self.handlers.register_all()

            # Schedule daily snapshot if enabled
            if plants_view and plants_view.get("daily_snapshot_enabled", False):
                await self.scheduler.schedule_daily_snapshot()

            # Restore active/scheduled timelapse after integration restart
            if plants_view and plants_view.get("isTimeLapseActive", False):
                await self.scheduler.restore_timelapse_after_restart()

            _LOGGER.info(
                f"{self.deviceName}: Camera initialized (storage: {storage_path})"
            )
            self._init_completed = True

        except Exception as e:
            _LOGGER.error(f"{self.deviceName}: Camera initialization failed: {e}")

    # =========================================================================
    # Capture Callbacks (for scheduler)
    # =========================================================================

    async def _capture_image(self, entity_id: str) -> Optional[str]:
        """Capture image callback for scheduler.

        Args:
            entity_id: Camera entity ID

        Returns:
            Base64-encoded image data or None
        """
        return await self.capture.capture_timelapse_image(entity_id)

    async def _emit_recording_status(
        self,
        is_recording: bool = False,
        is_scheduled: bool = False,
        is_night_mode: bool = False,
        capture_failed: bool = False,
    ) -> None:
        """Emit recording status event.

        Args:
            is_recording: Whether actively recording
            is_scheduled: Whether scheduled to start
            is_night_mode: Whether in night mode (lights off)
            capture_failed: Whether last capture failed
        """
        is_plant_day = self.dataStore.getDeep("isPlantDay.islightON")
        plants_view = self._get_plants_view() or {}
        capture_at_night = plants_view.get("capture_at_night", False)

        status_data = {
            "room": self.inRoom,
            "camera_entity": self.camera_entity_id,
            "is_recording": is_recording,
            "image_count": self.scheduler.tl_image_count,
            "start_time": (
                self.scheduler.tl_start_time.isoformat()
                if self.scheduler.tl_start_time else None
            ),
            "last_capture_time": (
                self.capture.last_capture_time.isoformat()
                if self.capture.last_capture_time else None
            ),
            "is_night_mode": is_night_mode or (
                not is_plant_day if not capture_at_night else False
            ),
            "capture_at_night_enabled": capture_at_night,
        }

        if is_scheduled:
            status_data["is_scheduled"] = is_scheduled
            status_data["scheduled_start"] = (
                self.scheduler.tl_start_time.isoformat()
                if self.scheduler.tl_start_time else None
            )
            status_data["scheduled_end"] = (
                self.scheduler.tl_end_time.isoformat()
                if self.scheduler.tl_end_time else None
            )

        if capture_failed:
            status_data["capture_failed"] = True

        await self.eventManager.emit(
            "CameraRecordingStatus",
            status_data,
            haEvent=True,
        )

    # =========================================================================
    # Internal Event Handlers
    # =========================================================================

    async def _handle_user_needs_image_internal(self, event) -> None:
        """Handle internal NeedViewPlant event."""
        # Create a mock event object for the handlers
        class MockEvent:
            def __init__(self, data):
                self.data = data

        await self.handlers._handle_user_needs_image(MockEvent(event if isinstance(event, dict) else {}))

    # =========================================================================
    # Public API Methods
    # =========================================================================

    async def startTL(self, resume=False, oldest_start_time=None):
        """Start timelapse capture using StartDate/EndDate from plantsView.

        Args:
            resume: If True, resume without resetting image count
            oldest_start_time: Optional override for start time
        """
        try:
            plants_view = self._get_plants_view() or {}
            start_str = plants_view.get("StartDate", "")
            end_str = plants_view.get("EndDate", "")

            start_dt = parse_datetime_value(start_str)
            end_dt = parse_datetime_value(end_str)

            if not start_dt or not end_dt:
                _LOGGER.error(
                    f"{self.deviceName}: Invalid StartDate or EndDate - cannot start timelapse"
                )
                await self.eventManager.emit(
                    "TimelapseError",
                    {
                        "device": self.deviceName,
                        "reason": "invalid_datetime",
                        "message": "Start date and end date must be valid ISO datetime strings",
                    },
                    haEvent=True,
                )
                return

            if oldest_start_time:
                start_dt = oldest_start_time

            await self.scheduler.start_timelapse(start_dt, end_dt, resume=resume)

            await self.eventManager.emit(
                "SaveState",
                {
                    "source": "Camera",
                    "device": self.deviceName,
                    "action": "start_recording" if not resume else "resume_recording",
                },
            )

        except Exception as e:
            _LOGGER.error(f"{self.deviceName}: Failed to start timelapse: {e}")

    # =========================================================================
    # Lifecycle Cleanup
    # =========================================================================

    async def async_cleanup(self):
        """Cleanup when camera device is being removed or HA is stopping.

        Cancels all scheduled tasks including daily snapshots and background generation.
        """
        try:
            # Cleanup scheduler (stops timelapse and daily snapshots)
            await self.scheduler.cleanup()

            # Cancel background video generation
            await self.video_gen.cancel_generation()

            _LOGGER.info(f"{self.deviceName}: Camera cleanup completed")

        except Exception as e:
            _LOGGER.error(f"{self.deviceName}: Error during cleanup: {e}")
