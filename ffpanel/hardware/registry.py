from .types import BackendCapabilities, FFmpegInventory, HardwareBackend, HardwareProfile


class HardwareRegistry:
    def __init__(self, backends: tuple[HardwareBackend, ...]) -> None:
        self.backends: dict[str, HardwareBackend] = {}
        self.profiles: dict[str, HardwareProfile] = {}
        for backend in backends:
            if backend.id in self.backends:
                raise ValueError(f"Duplicate backend: {backend.id}")
            self.backends[backend.id] = backend
            for profile in backend.profiles():
                if profile.backend_id != backend.id:
                    raise ValueError(f"Profile backend mismatch: {profile.id}")
                if profile.id in self.profiles:
                    raise ValueError(f"Duplicate profile: {profile.id}")
                self.profiles[profile.id] = profile
        for profile in self.profiles.values():
            if profile.fallback is not None and profile.fallback not in self.profiles:
                raise ValueError(f"Unknown fallback: {profile.fallback}")
        for profile_id in self.profiles:
            self.mode_chain(profile_id)

    @property
    def device_paths(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                path for backend in self.backends.values() for path in backend.device_paths
            )
        )

    def probe(self, inventory: FFmpegInventory) -> dict[str, BackendCapabilities]:
        return {key: backend.probe(inventory) for key, backend in self.backends.items()}

    def backend_for(self, profile_id: str) -> HardwareBackend:
        return self.backends[self.profiles[profile_id].backend_id]

    def label(self, profile_id: str) -> str:
        return self.profiles[profile_id].label

    def mode_chain(self, profile_id: str, auto_fallback: bool = True) -> tuple[str, ...]:
        chain: list[str] = []
        current: str | None = profile_id
        while current is not None:
            if current in chain:
                raise ValueError(f"Cyclic fallback: {current}")
            profile = self.profiles[current]
            chain.append(current)
            current = profile.fallback if auto_fallback else None
        return tuple(chain)
