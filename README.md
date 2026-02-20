# ICE_PLANT_VIEWER
Client-facing viewer for the ICE_PLANT remote monitoring dongle.

## Highlights
- Time-domain plot shows the raw HR1/HR2/MHR samples.
- Spectrogram is a **waterfall**: newest row at the top, moving down with time.
- Live spectrogram rows are plotted **only from live data**; prefilled history is used only to compute the first row so you don't wait for the window to fill.

## Spectrogram Controls
- `Spec Window (s)`: FFT window length (16, 32, 60, 180, 300 seconds). Longer windows give better frequency resolution.
- `Freq Range (Hz)`: Display range (0–0.5, 0–1.0, 0–2.0 Hz).

## Live Prefill Behavior
On connect, the app fetches prior data from the current remote file (based on timestamps) to fill the FFT window. The waterfall display itself starts from the top and only shows rows from live samples.
