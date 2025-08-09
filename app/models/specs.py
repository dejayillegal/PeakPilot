from dataclasses import dataclass


@dataclass
class LoudnormSpec:
    name: str
    I: float
    TP: float
    LRA: float
    sr: int
    bit_depth: int = 24


club = LoudnormSpec("Club", I=-7.2, TP=-0.8, LRA=7, sr=48000)
streaming = LoudnormSpec("Streaming", I=-9.5, TP=-1.0, LRA=9, sr=44100)

# unlimited premaster handled separately
