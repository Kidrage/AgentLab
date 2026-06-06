import numpy as np

def render_4ch(layers, routing, sample_rate):
    """
    Render spatial layers to 4-channel output (LF, RF, LB, RB)
    
    Args:
        layers: Dictionary containing all five spatial layers
        routing: Routing parameters for each layer
        sample_rate: Audio sample rate
    
    Returns:
        4-channel numpy array with rendered output
    """
    # Get the length of the audio from one of the layers
    length = len(next(iter(layers.values())))
    
    # Initialize output channels
    output = np.zeros((length, 4), dtype=np.float32)
    
    # Process each layer
    for layer_name, layer_data in layers.items():
        # Get routing parameters for this layer
        params = routing[layer_name]
        front_gain = params['front_gain']
        rear_gain = params['rear_gain']
        decorrelation = params['decorrelation']
        
        # Apply decorrelation if needed
        if decorrelation > 0 and layer_data.size > 0:
            layer_data = apply_decorrelation(layer_data, decorrelation, sample_rate)
        
        # Distribute to channels
        if front_gain > 0:
            output[:, 0] += layer_data * front_gain  # LF
            output[:, 1] += layer_data * front_gain  # RF
        
        if rear_gain > 0:
            output[:, 2] += layer_data * rear_gain  # LB
            output[:, 3] += layer_data * rear_gain  # RB
    
    return output

def apply_decorrelation(signal, strength, sample_rate):
    """
    Apply decorrelation to create diffuse sound without obvious echoes
    
    Args:
        signal: Input audio signal
        strength: Decorrelation strength (0-1)
        sample_rate: Audio sample rate
    
    Returns:
        Decorrelated audio signal
    """
    if strength <= 0 or signal.size == 0:
        return signal
    
    # Calculate delay in samples
    delay_samples_lb = int(0.012 * sample_rate)  # 12ms for LB
    delay_samples_rb = int(0.016 * sample_rate)  # 16ms for RB
    
    # Ensure we don't exceed signal length
    if delay_samples_lb >= len(signal) or delay_samples_rb >= len(signal):
        return np.zeros_like(signal)
    
    # Initialize decorrelated signals
    lb_signal = np.zeros_like(signal)
    rb_signal = np.zeros_like(signal)
    
    # Feedback coefficient
    feedback = 0.7 * strength
    
    # All-pass filter with different delays for LB and RB
    for i in range(len(signal)):
        if i >= delay_samples_lb:
            lb_signal[i] = signal[i] * 0.5 + lb_signal[i - delay_samples_lb] * feedback
        
        else:
            lb_signal[i] = signal[i] * 0.5
        
        if i >= delay_samples_rb:
            rb_signal[i] = signal[i] * 0.5 + rb_signal[i - delay_samples_rb] * feedback
        
        else:
            rb_signal[i] = signal[i] * 0.5
    
    # Find minimum length of delayed signals
    min_len = min(len(signal) - delay_samples_lb, len(signal) - delay_samples_rb)
    
    # Ensure min_len is not negative
    min_len = max(0, min_len)
    
    # Combine LB and RB signals with cross-talk for diffusion
    combined = np.zeros(min_len, dtype=np.float32)
    combined = (lb_signal[delay_samples_lb:delay_samples_lb + min_len] + 
                rb_signal[delay_samples_rb:delay_samples_rb + min_len]) * 0.7
    
    # Create output array and copy combined signal
    output = np.zeros_like(signal)
    output[:min_len] = combined
    
    return output