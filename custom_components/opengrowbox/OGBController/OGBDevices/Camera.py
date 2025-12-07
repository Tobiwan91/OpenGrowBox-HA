from .Device import Device
import logging

_LOGGER = logging.getLogger(__name__)

class Camera(Device):
    def __init__(self, deviceName, deviceData, eventManager, dataStore, deviceType, inRoom, hass=None, deviceLabel="EMPTY", allLabels=[]):
        super().__init__(deviceName, deviceData, eventManager, dataStore, deviceType, inRoom, hass, deviceLabel, allLabels)
  
        self.log_action("Camera device initialized")
    
    async def deviceInit(self, entitys):
        """Initialize camera device and identify camera entities."""
        await super().deviceInit(entitys)
        
        # Auto-detect camera entities from device data
        camera_entities = []
        for entity in entitys:
            if hasattr(entity, 'attributes') and entity.attributes:
                # Check if this is a camera entity based on attributes
                if entity.attributes.get('device_class') == 'camera' or 'camera' in str(entity.entity_id).lower():
                    camera_entities.append(entity)
        
        # Store camera entities for later use
        self.camera_entities = camera_entities
        
        # Set initial camera state based on entities
        if camera_entities:
            self.log_action(f"Found {len(camera_entities)} camera entities")
    
    def log_action(self, action_name):
        """Protokolliert die ausgef�hrte Aktion."""
        state = self.getCameraState()
        log_message = f"Recording:{state['is_recording']} Streaming:{state['is_streaming']} Entities:{state['entity_count']}"
        _LOGGER.info(f"{action_name}: {self.deviceName} - {log_message}")
