"""Bounded AVD hardware settings shared by admission and worker execution."""
from pydantic import Field, model_validator

from .run_models import Contract


class EmulatorHardware(Contract):
    width: int = Field(default=720, ge=320, le=2560)
    height: int = Field(default=1280, ge=320, le=3200)
    density: int = Field(default=320, ge=120, le=640)
    ram_mb: int = Field(default=1536, ge=1024, le=8192)
    cpu_cores: int = Field(default=2, ge=1, le=8)
    storage_gb: int = Field(default=8, ge=2, le=64)

    @model_validator(mode='after')
    def coherent_hardware(self):
        if self.width % 8 or self.height % 8 or self.width * self.height > 4_194_304:
            raise ValueError('Screen dimensions must be multiples of 8 and at most four megapixels')
        if self.ram_mb % 256:
            raise ValueError('RAM must be a multiple of 256 MiB')
        if max(self.width, self.height) > min(self.width, self.height) * 3.2:
            raise ValueError('Screen aspect ratio must not exceed 3.2')
        return self


DEFAULT_HARDWARE = EmulatorHardware().model_dump()


def hardware_config(value=None):
    return EmulatorHardware.model_validate({} if value is None else value).model_dump()


def applied_profile(value):
    """Old workers stored requested disk size; never expose it as an observation."""
    if value is None:
        return None
    capacity = value.get('storage_capacity_bytes')
    if type(capacity) is not int or not 0 < capacity <= 1_125_899_906_842_624:
        capacity = None
    return {**{key:value[key] for key in DEFAULT_HARDWARE if key!='storage_gb' and key in value},
            'storage_capacity_bytes':capacity}
