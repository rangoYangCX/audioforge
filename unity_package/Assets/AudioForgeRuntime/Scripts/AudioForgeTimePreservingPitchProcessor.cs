using UnityEngine;

public static class AudioForgeTimePreservingPitchProcessor
{
    public static AudioClip CreatePitchShiftedClip(AudioClip sourceClip, int pitchCents, string generatedClipName)
    {
        if (sourceClip == null || pitchCents == 0)
        {
            return sourceClip;
        }

        float pitchRatio = Mathf.Pow(2f, pitchCents / 1200f);
        if (pitchRatio <= 0f)
        {
            return sourceClip;
        }

        int sampleFrames = sourceClip.samples;
        int channels = Mathf.Max(1, sourceClip.channels);
        int frequency = sourceClip.frequency;
        float[] sourceData = new float[sampleFrames * channels];
        if (!sourceClip.GetData(sourceData, 0))
        {
            return sourceClip;
        }

        float[] processedData = new float[sourceData.Length];
        for (int channelIndex = 0; channelIndex < channels; channelIndex += 1)
        {
            float[] channelData = ExtractChannel(sourceData, channels, channelIndex);
            float[] pitchShifted = ResampleLinear(channelData, Mathf.Max(1, Mathf.RoundToInt(channelData.Length / pitchRatio)));
            float[] stretched = TimeStretch(channelData.Length, pitchShifted);
            WriteChannel(processedData, channels, channelIndex, stretched);
        }

        AudioClip generatedClip = AudioClip.Create(generatedClipName, sampleFrames, channels, frequency, false);
        generatedClip.SetData(processedData, 0);
        return generatedClip;
    }

    private static float[] ExtractChannel(float[] interleaved, int channels, int channelIndex)
    {
        float[] channelData = new float[interleaved.Length / channels];
        for (int frameIndex = 0; frameIndex < channelData.Length; frameIndex += 1)
        {
            channelData[frameIndex] = interleaved[(frameIndex * channels) + channelIndex];
        }

        return channelData;
    }

    private static void WriteChannel(float[] interleaved, int channels, int channelIndex, float[] channelData)
    {
        int frameCount = Mathf.Min(channelData.Length, interleaved.Length / channels);
        for (int frameIndex = 0; frameIndex < frameCount; frameIndex += 1)
        {
            interleaved[(frameIndex * channels) + channelIndex] = Mathf.Clamp(channelData[frameIndex], -1f, 1f);
        }
    }

    private static float[] ResampleLinear(float[] samples, int targetLength)
    {
        if (samples.Length == 0 || targetLength <= 0)
        {
            return new float[0];
        }

        if (samples.Length == targetLength)
        {
            float[] copy = new float[samples.Length];
            System.Array.Copy(samples, copy, samples.Length);
            return copy;
        }

        float[] output = new float[targetLength];
        float scale = (samples.Length - 1f) / Mathf.Max(1f, targetLength - 1f);
        for (int index = 0; index < targetLength; index += 1)
        {
            float sourcePosition = index * scale;
            int leftIndex = Mathf.Clamp(Mathf.FloorToInt(sourcePosition), 0, samples.Length - 1);
            int rightIndex = Mathf.Min(leftIndex + 1, samples.Length - 1);
            float alpha = sourcePosition - leftIndex;
            output[index] = Mathf.Lerp(samples[leftIndex], samples[rightIndex], alpha);
        }

        return output;
    }

    private static float[] TimeStretch(int targetLength, float[] samples)
    {
        if (samples.Length == 0 || targetLength <= 0)
        {
            return new float[0];
        }

        if (samples.Length == targetLength)
        {
            return samples;
        }

        int windowSize = Mathf.Clamp(Mathf.NextPowerOfTwo(Mathf.Max(128, samples.Length / 8)), 256, 2048);
        if (windowSize >= samples.Length)
        {
            return FitLength(samples, targetLength);
        }

        int overlapSize = windowSize / 2;
        int synthesisHop = Mathf.Max(32, windowSize - overlapSize);
        float stretchRatio = targetLength / (float)samples.Length;
        int analysisHop = Mathf.Max(1, Mathf.RoundToInt(synthesisHop / stretchRatio));
        int searchRadius = Mathf.Max(8, analysisHop / 2);

        float[] window = BuildHannWindow(windowSize);
        float[] output = new float[targetLength + windowSize];
        float[] normalization = new float[targetLength + windowSize];

        int inputPosition = 0;
        int outputPosition = 0;
        bool isFirstFrame = true;

        while (inputPosition + windowSize < samples.Length && outputPosition + windowSize < output.Length)
        {
            int actualInputPosition = inputPosition;
            if (!isFirstFrame)
            {
                actualInputPosition = FindBestOverlapPosition(samples, inputPosition, output, outputPosition, overlapSize, searchRadius);
            }

            for (int index = 0; index < windowSize; index += 1)
            {
                float weight = window[index];
                output[outputPosition + index] += samples[actualInputPosition + index] * weight;
                normalization[outputPosition + index] += weight * weight;
            }

            inputPosition = actualInputPosition + analysisHop;
            outputPosition += synthesisHop;
            isFirstFrame = false;
        }

        float[] fitted = new float[targetLength];
        for (int index = 0; index < fitted.Length; index += 1)
        {
            if (normalization[index] > 1e-6f)
            {
                fitted[index] = output[index] / normalization[index];
            }
        }

        return FitLength(fitted, targetLength);
    }

    private static int FindBestOverlapPosition(float[] input, int expectedInputPosition, float[] output, int outputPosition, int overlapSize, int searchRadius)
    {
        int minimum = Mathf.Max(0, expectedInputPosition - searchRadius);
        int maximum = Mathf.Min(input.Length - overlapSize - 1, expectedInputPosition + searchRadius);
        int bestPosition = Mathf.Clamp(expectedInputPosition, minimum, maximum);
        float bestScore = float.NegativeInfinity;

        for (int candidate = minimum; candidate <= maximum; candidate += 1)
        {
            float score = 0f;
            for (int index = 0; index < overlapSize; index += 1)
            {
                score += output[outputPosition + index] * input[candidate + index];
            }

            if (score > bestScore)
            {
                bestScore = score;
                bestPosition = candidate;
            }
        }

        return bestPosition;
    }

    private static float[] BuildHannWindow(int size)
    {
        float[] window = new float[size];
        for (int index = 0; index < size; index += 1)
        {
            window[index] = 0.5f - (0.5f * Mathf.Cos((2f * Mathf.PI * index) / Mathf.Max(1, size - 1)));
        }

        return window;
    }

    private static float[] FitLength(float[] samples, int targetLength)
    {
        if (samples.Length == targetLength)
        {
            return samples;
        }

        float[] fitted = new float[targetLength];
        int copyLength = Mathf.Min(samples.Length, targetLength);
        System.Array.Copy(samples, fitted, copyLength);
        return fitted;
    }
}