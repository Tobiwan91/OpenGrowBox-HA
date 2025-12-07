from homeassistant.components.camera import Camera as HACamera
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity
import logging
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class CustomCamera(HACamera, RestoreEntity):
    """Custom camera for OpenGrowBox integration."""

    def __init__(self, name, room_name, coordinator, camera_entity_id=None):
        """Initialize the camera."""
        self._name = name
        self.room_name = room_name
        self.coordinator = coordinator
        self._camera_entity_id = camera_entity_id
        self._unique_id = f"{DOMAIN}_{room_name}_{name.lower().replace(" ", "_")}"
        self._available = True
        self._attr_motion_detection_enabled = False
        self._model = "OpenGrowBox Camera"
        self._brand = "OpenGrowBox"

    @property
    def unique_id(self):
        """Return the unique ID for this entity."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def available(self):
        """Return True if entity is available."""
        return self._available

    @property
    def device_info(self):
        """Return device information to link this entity to a device."""
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": f"Camera for {self.room_name}",
            "model": self._model,
            "manufacturer": self._brand,
            "suggested_area": self.room_name,
        }

    @property
    def extra_state_attributes(self):
        """Return extra attributes for the entity."""
        attrs = {"room_name": self.room_name}
        if self._camera_entity_id:
            attrs["source_entity_id"] = self._camera_entity_id
        return attrs

    async def async_camera_image(self):
        """Return bytes of camera image."""
        if not self.hass or not self._camera_entity_id:
            return None
            
        try:
            # Get the image from the source camera entity
            from homeassistant.components import camera
            source_state = self.hass.states.get(self._camera_entity_id)
            
            if source_state:
                # Use the camera component to get the image
                image_bytes = await camera.async_get_image(self.hass, self._camera_entity_id)
                return image_bytes
        except Exception as e:
            _LOGGER.error(f"Error getting camera image: {e}")
            
        return None

    def camera_image(self):
        """Return bytes of camera image."""
        return None  # Use async version

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up camera entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    cameras = []
    
    # Look for camera devices in the room
    ogb_controller = coordinator.ogb_controller
    if ogb_controller:
        device_manager = ogb_controller.device_manager
        
        # Get all devices and filter for cameras
        for device_name, device in device_manager.devices.items():
            if hasattr(device, "deviceType") and device.deviceType == "Camera":
                camera_entity_id = device.get_camera_entity_id()
                camera_name = device.get_camera_name() or f"Camera {device_name}"
                
                # Create camera entity
                camera = CustomCamera(
                    f"OGB_Camera_{device_name}",
                    device.inRoom,
                    coordinator,
                    camera_entity_id
                )
                cameras.append(camera)
        
    if cameras:
        async_add_entities(cameras, True)
        _LOGGER.info(f"Added {len(cameras)} camera entities")
    
    return True
