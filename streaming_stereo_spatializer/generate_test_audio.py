import numpy as np
import soundfile as sf

# Generate a 2-second stereo test tone
sample_rate = 44100
duration = 2.0
t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

# Create a stereo signal with a 440Hz tone in left channel and 523Hz in right
left = np.sin(2 * np.pi * 440 * t)  # A4 note
right = np.sin(2 * np.pi * 523 * t)  # C5 note

# Combine to stereo signal
audio = np.column_stack((left, right))

# Export to WAV file
sf.write('test_input.wav', audio, sample_rate, subtype='FLOAT')

print("Generated test_input.wav in current directory")