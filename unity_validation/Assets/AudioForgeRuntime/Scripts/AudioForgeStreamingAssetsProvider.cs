using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// 默认参考资源提供器。
/// 按 StreamingAssets/AudioForge/Assets/<AssetKey>.<RuntimeAudioFormat> 读取导出音频。
/// </summary>
public sealed class AudioForgeStreamingAssetsProvider : IAudioForgeResourceProvider
{
    private readonly string _assetsRoot;

    public AudioForgeStreamingAssetsProvider(string assetsRoot)
    {
        _assetsRoot = assetsRoot;
    }

    public IEnumerator LoadClip(string assetKey, string runtimeAudioFormat, Action<AudioClip> onLoaded)
    {
        string format = string.IsNullOrWhiteSpace(runtimeAudioFormat) ? "ogg" : runtimeAudioFormat;
        string fullPath = Path.Combine(_assetsRoot, assetKey + "." + format);
        if (!File.Exists(fullPath))
        {
            fullPath = Path.Combine(_assetsRoot, assetKey + ".wav");
        }

        if (!File.Exists(fullPath))
        {
            Debug.LogError("AudioForge resource file not found: " + fullPath);
            onLoaded(null);
            yield break;
        }

        UnityWebRequest request = UnityWebRequestMultimedia.GetAudioClip("file://" + fullPath.Replace("\\", "/"), AudioType.UNKNOWN);
        yield return request.SendWebRequest();
        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError("AudioForge resource request failed: " + request.error + " path=" + fullPath);
            onLoaded(null);
            request.Dispose();
            yield break;
        }

        AudioClip clip = DownloadHandlerAudioClip.GetContent(request);
        onLoaded(clip);
        request.Dispose();
    }
}