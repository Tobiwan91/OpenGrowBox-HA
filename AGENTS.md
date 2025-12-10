# OpenGrowBox-HA Agent Guidelines

## Project Overview
This is a Home Assistant custom integration for OpenGrowBox automation and control.

## Project Structure
- custom_components/opengrowbox/ - Main integration code
- custom_components/opengrowbox/OGBController/ - Core controller logic
- custom_components/opengrowbox/OGBDevices/ - Device implementations
- custom_components/opengrowbox/frontend/ - React-based GUI
- docs/ - Documentation

## Key Architecture Components

### Core Controller
- OGB.py - Main orchestrator (1,836 lines)
- coordinator.py - HA integration coordinator
- RegistryListener.py - Entity change monitoring

### Device Classes
All devices inherit from Device.py base class:
- Sensor devices: Sensor.py, ModbusSensor.py
- Control devices: Light.py, Climate.py, CO2.py, Humidifier.py, Dehumidifier.py
- Flow devices: Pump.py, Exhaust.py, Intake.py, Ventilation.py
- Specialized: Heater.py, Cooler.py, Fridge.py

### Managers
- DeviceManager.py - Device lifecycle management
- ModeManager.py - Growth mode automation
- ActionManager.py - Action execution
- PremManager.py - Premium features
- EventManager.py - Event handling

### Data Classes
- OGBData.py - Configuration and state
- OGBPublications.py - Event definitions
- OGBMedium.py - Medium management

## Coding Conventions

### Python Style
- Follow PEP 8 standards
- Use async/await for all I/O operations
- German comments mixed with English (existing pattern)
- Logging with _LOGGER module-level logger

### Naming Conventions
- Classes: PascalCase (e.g., OpenGrowBox)
- Functions/variables: snake_case (e.g., device_manager)
- Constants: UPPER_SNAKE_CASE (e.g., DOMAIN)
- Private methods: prefix with underscore

### File Organization
- Each device class in separate file
- Utility functions in utils/ directory
- Parameters and translations in OGBParams/

## Important Implementation Notes

### Async/Await Patterns
All HA integration methods must be async:
async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    # Implementation

### Event System
The project uses a custom event system:
self.eventManager.on('EventName', callback_function)

### Device Initialization
Devices follow this pattern:
1. Initialize with device data
2. Register event listeners
3. Set up sensors/switches
4. Start monitoring

### Data Storage
Use DataStore for persistence:
self.dataStore.setDeep('path.to.data', value)
value = self.dataStore.getDeep('path.to.data')

## Testing Guidelines
- Test device classes independently
- Mock Home Assistant entities in unit tests
- Verify async behavior with proper event loops

## Frontend Development
- React-based SPA in frontend/static/static/js/main.js
- Styled-components for CSS
- Custom web component integration with HA

## Service Definitions
Services are defined in services.yaml:
- update_sensor - Update sensor values
- toggle_switch - Toggle switch states
- update_date/time/text - Update entity values
- add/remove_select_options - Manage select options

## Premium Features
Premium functionality uses WebSocket connection:
- wss://prem.opengrowbox.net
- Secure authentication required
- Separate proprietary license

## Configuration Flow
Simple room-based setup:
1. User enters room name
2. Integration discovers devices in room
3. Groups devices by ogb prefix
4. Starts automation controllers

## Common Patterns

### Device Registration
# Register device with Home Assistant
self.hass.states.async_set(entity_id, state, attributes)

### Sensor Updates
# Update sensor via service
await update_sensor_via_service(self.hass, entity_id, value)

### Error Handling
try:
    # Operation
except Exception as e:
    _LOGGER.error(f'Error description: {e}')

## Environment Requirements
- Home Assistant >= 2024.10.1
- Python 3.9+
- No external dependencies (uses HA built-ins)

## Version Management
- Version defined in const.py and manifest.json
- Maintain semantic versioning
- Update both files consistently

## When Making Changes
1. Check existing German comments for context
2. Follow async patterns throughout
3. Use proper error handling and logging
4. Test with real HA entities when possible
5. Consider premium vs free feature separation
6. Update service definitions if adding new services
7. Maintain backward compatibility

## Debugging Tips
- Enable debug logging for opengrowbox domain
- Check HA logs for device initialization errors
- Verify entity IDs follow naming conventions
- Test service calls manually in HA dev tools
