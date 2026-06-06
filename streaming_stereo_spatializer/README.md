# Streaming Stereo Spatializer

## Overview

This project implements a **non-AI streaming stereo spatializer** for a 4.0 speaker system. It converts stereo L/R audio into five spatial layers that are rendered to logical 4.0 output (left front, right front, left back, right back).

This is **not** AI-based source separation. The spatial layers are not clean stems but rather spatial-function buses used for rendering.

## Key Features

- Converts stereo L/R audio to 4.0 spatial output
- Five spatial layers:
  - Bass Layer (low-frequency body)
  - Front Core (center-correlated content)
  - Side Width (stereo difference)
  - Rear Ambience (diffuse, low-coherence)
  - High Air (high-frequency content)
- Multiple presets for different spatialization styles
- Energy matching to maintain consistent loudness
- Limiter to prevent clipping
- Diagnostic output for analysis

## Installation

1. Clone this repository
2. Install dependencies:
```bash
pip install numpy librosa soundfile scipy
```

## Usage

To run with the generated test audio:
```bash
cd streaming_stereo_spatializer
python generate_test_audio.py  # Creates test_input.wav
python run_spatializer.py test_input.wav --out output_4ch.wav --preset natural --analysis-seconds 2.0 --export-preview --export-diagnostics
```

For your own audio files:
```bash
python run_spatializer.py input.wav --out output_4ch.wav --preset natural --analysis-seconds 2.0 --export-preview --export-diagnostics
```

### Arguments
- `input.wav`: Path to input stereo WAV file
- `--out`: Path to output 4-channel WAV file
- `--preset`: Spatialization preset (auto/natural/wide/vocal_safe/live/club/bypass/ms_baseline)
- `--analysis-seconds`: Duration of analysis (default: 2.0)
- `--export-preview`: Export stereo preview downmix
- `--export-diagnostics`: Export JSON diagnostics file

## Presets

- **natural**: Balanced default mode
- **wide**: More obvious spatial effect
- **vocal_safe**: For vocal-heavy music
- **live**: For live/acoustic recordings
- **club**: For electronic/bass-heavy music
- **bypass**: No spatialization
- **ms_baseline**: Simple M/S baseline for comparison

## Listening to 4-Channel Audio

Most consumer audio equipment is stereo. To listen to the 4-channel output:

1. Use a surround sound system with 4 speakers
2. Use headphones with a virtual surround sound processor
3. Use audio software that supports 4-channel playback

## Tuning Presets

To tune presets:
1. Modify the routing parameters in `presets.py`
2. Adjust the layer routing logic in `layer_router.py`
3. Experiment with different decorrelation settings in `decorrelator.py`
4. Use the diagnostic output to understand the impact of changes

## File Structure

```
streaming_stereo_spatializer/
│
├── run_spatializer.py        # Main script
├── audio_io.py               # Audio loading and export
├── streaming_analyzer.py     # Audio analysis
├── layer_extractor.py        # Layer extraction
├── layer_router.py           # Layer routing
├── decorrelator.py           # Rear ambience decorrelation
├── renderer_4ch.py           # 4-channel rendering
├── energy_manager.py         # Loudness matching
├── limiter.py                # Clipping prevention
├── diagnostics.py            # Diagnostic output
├── presets.py                # Spatialization presets
├── generate_test_audio.py    # Test tone generation
├── README.md                 # This file
```

## Implementation Notes

- The system is designed to resemble a streaming PCM processor
- It uses a rule-based approach rather than AI
- The architecture prioritizes stable front image and bass protection
- Rear ambience is designed to feel wide without obvious echoes
- Energy management prevents output from becoming louder than input

## Limitations

- This is a simulation, not real hardware
- It doesn't handle physical speaker calibration
- The presets need to be tuned based on listening experience
- It doesn't implement advanced features like Dolby Atmos metadata
- It's not designed for network streaming or hardware distribution

## Why Not AI?

This project is explicitly not AI-based. It uses simple signal processing techniques to extract spatial characteristics from stereo audio. The spatial layers are not clean stems but rather spatial-function buses used for rendering to a 4.0 speaker system.

## Next Steps

To evaluate the system:

1. Compare original stereo vs bypass vs ms_baseline vs natural vs wide
2. Test with different music genres
3. Adjust presets based on listening experience
4. Add visualization of spatial characteristics
5. Implement more advanced decorrelation techniques