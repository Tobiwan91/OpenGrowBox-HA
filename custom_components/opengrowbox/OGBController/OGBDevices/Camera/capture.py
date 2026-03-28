"""
Camera capture module.

Handles image capture from Home Assistant camera entities with retry logic.
"""

import base64
import asyncio
import logging
from typing import Optional, List

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_RETRY_DELAYS = [5, 15, 30]
DEFAULT_MAX_RETRIES = 3


class CameraCapture:
    """Handles camera image capture with retry logic."""

    def __init__(
        self,
        hass,
        device_name: str,
        in_room: str,
        event_manager,
    ):
        """Initialize camera capture.

        Args:
            hass: Home Assistant instance
            device_name: Camera device name for logging
            in_room: Room identifier
            event_manager: Event manager for emitting events
        """
        self.hass = hass
        self.device_name = device_name
        self.in_room = in_room
        self.event_manager = event_manager

        # Cache
        self.last_image: Optional[str] = None
        self.last_capture_time = None

    # =========================================================================
    # Core Capture Methods
    # =========================================================================

    async def get_ha_camera_image(self, entity_id: str) -> Optional[str]:
        """Get image from HA camera entity directly via component API.

        Args:
            entity_id: Home Assistant camera entity ID

        Returns:
            Base64-encoded image data or None on failure
        """
        try:
            if not self.hass:
                _LOGGER.error(f"{self.device_name}: No HA instance available")
                return None

            from homeassistant.components.camera import async_get_image

            _LOGGER.debug(
                f"{self.device_name}: Fetching image from {entity_id} via HA API"
            )

            image = await async_get_image(self.hass, entity_id)

            if image and image.content:
                image_base64 = base64.b64encode(image.content).decode("utf-8")
                _LOGGER.debug(
                    f"{self.device_name}: Successfully captured image from {entity_id} "
                    f"({len(image.content)} bytes)"
                )
                return image_base64
            else:
                _LOGGER.warning(f"{self.device_name}: No image content from {entity_id}")
                return None

        except Exception as e:
            _LOGGER.error(f"{self.device_name}: Error fetching HA camera image: {e}")
            return None

    async def capture_with_retry(
        self,
        entity_id: str,
        retry_delays: List[int] = None,
        capture_type: str = "capture",
        update_cache: bool = True,
        clear_cache: bool = False,
    ) -> Optional[str]:
        """Capture image with exponential backoff retry.

        Unified capture method for both daily snapshots and timelapse images.

        Args:
            entity_id: Home Assistant camera entity ID
            retry_delays: List of delays between retries in seconds (default: [5, 15, 30])
            capture_type: Type of capture for logging ("daily" or "timelapse")
            update_cache: Whether to update last_image/last_capture_time on success
            clear_cache: Whether to clear cache before capture (for timelapse)

        Returns:
            Base64-encoded image data on success, None on failure
        """
        if retry_delays is None:
            retry_delays = DEFAULT_RETRY_DELAYS

        # Clear cache if requested (prevents saving old data on failure)
        if clear_cache:
            self.last_image = None

        for attempt, delay in enumerate(retry_delays):
            try:
                _LOGGER.debug(
                    f"{self.device_name}: {capture_type.capitalize()} capture attempt "
                    f"{attempt + 1}/{len(retry_delays)}"
                )

                image_data = await self.get_ha_camera_image(entity_id)

                if image_data:
                    if update_cache:
                        self.last_image = image_data
                        self.last_capture_time = dt_util.now()

                    _LOGGER.info(
                        f"{self.device_name}: {capture_type.capitalize()} captured "
                        f"successfully (attempt {attempt + 1})"
                    )
                    return image_data
                else:
                    _LOGGER.warning(
                        f"{self.device_name}: {capture_type.capitalize()} attempt "
                        f"{attempt + 1} returned no image data"
                    )

            except Exception as e:
                _LOGGER.warning(
                    f"{self.device_name}: {capture_type.capitalize()} attempt "
                    f"{attempt + 1} failed: {e}"
                )

            # Retry with delay if not last attempt
            if attempt < len(retry_delays) - 1:
                _LOGGER.info(
                    f"{self.device_name}: Retrying {capture_type} capture in "
                    f"{delay} seconds..."
                )
                await asyncio.sleep(delay)

        # All retries failed
        _LOGGER.error(
            f"{self.device_name}: {capture_type.capitalize()} capture failed after "
            f"{len(retry_delays)} attempts"
        )
        return None

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    async def capture_daily_snapshot(
        self,
        entity_id: str,
    ) -> Optional[str]:
        """Capture daily snapshot with 3-retry exponential backoff.

        Args:
            entity_id: Home Assistant camera entity ID

        Returns:
            Base64-encoded image data on success, None on failure
        """
        image_data = await self.capture_with_retry(
            entity_id=entity_id,
            retry_delays=DEFAULT_RETRY_DELAYS,
            capture_type="daily",
            update_cache=True,
            clear_cache=False,
        )

        if not image_data:
            await self.event_manager.emit(
                "ogb_camera_capture_failed",
                {
                    "device": self.device_name,
                    "room": self.in_room,
                    "camera_entity": entity_id,
                    "error": f"Failed after {DEFAULT_MAX_RETRIES} retry attempts",
                    "retry_count": DEFAULT_MAX_RETRIES,
                    "capture_type": "daily",
                },
                haEvent=True,
            )

        return image_data

    async def capture_timelapse_image(
        self,
        entity_id: str,
    ) -> Optional[str]:
        """Capture timelapse image with 3-retry exponential backoff.

        Args:
            entity_id: Home Assistant camera entity ID

        Returns:
            Base64-encoded image data on success, None on failure
        """
        image_data = await self.capture_with_retry(
            entity_id=entity_id,
            retry_delays=DEFAULT_RETRY_DELAYS,
            capture_type="timelapse",
            update_cache=True,
            clear_cache=True,  # Clear cache to prevent saving old data on failure
        )

        if not image_data:
            await self.event_manager.emit(
                "ogb_camera_capture_failed",
                {
                    "device": self.device_name,
                    "room": self.in_room,
                    "camera_entity": entity_id,
                    "error": f"Failed after {DEFAULT_MAX_RETRIES} retry attempts",
                    "retry_count": DEFAULT_MAX_RETRIES,
                    "capture_type": "timelapse",
                },
                haEvent=True,
            )

        return image_data

    # =========================================================================
    # Cache Management
    # =========================================================================

    def get_cached_image(self, max_age_minutes: int = 5) -> Optional[str]:
        """Get cached image if still valid.

        Args:
            max_age_minutes: Maximum age of cached image in minutes

        Returns:
            Cached image data if valid, None otherwise
        """
        if self.last_image is None or self.last_capture_time is None:
            return None

        from datetime import timedelta
        cutoff = dt_util.now() - timedelta(minutes=max_age_minutes)

        if self.last_capture_time > cutoff:
            return self.last_image

        return None

    def clear_cache(self) -> None:
        """Clear cached image data."""
        self.last_image = None
        self.last_capture_time = None
