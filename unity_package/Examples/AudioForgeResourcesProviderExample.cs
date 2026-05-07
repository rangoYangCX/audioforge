using System;
using System.Collections;
using UnityEngine;

/// <summary>
/// 示例：把 AudioForge 的资源加载层接到项目自己的加载系统。
/// 这里用 Resources 演示接口形状，因为它不需要额外第三方依赖；
/// 生产项目更建议替换成 Addressables、AssetBundle 或自建下载层。
/// </summary>
public sealed class AudioForgeResourcesProviderExample : IAudioForgeResourceProvider
{
    private readonly string _resourcesRoot;

    public AudioForgeResourcesProviderExample(string resourcesRoot = "AudioForge")
    {
        _resourcesRoot = string.IsNullOrWhiteSpace(resourcesRoot) ? "AudioForge" : resourcesRoot.Trim('/');
    }

    public IEnumerator LoadClip(string assetKey, string runtimeAudioFormat, Action<AudioClip> onLoaded)
    {
        // AudioForge 的 assetKey 默认按 '/' 分层，例如 ui/click_01。
        // 如果你要走 Resources，可以在构建阶段把导出资源转成同名目录结构，再按 assetKey 直接查找。
        string resourcesPath = _resourcesRoot + "/" + assetKey;
        ResourceRequest request = Resources.LoadAsync<AudioClip>(resourcesPath);
        yield return request;

        AudioClip clip = request.asset as AudioClip;
        if (clip == null)
        {
            Debug.LogError(
                "AudioForge Resources clip not found: " + resourcesPath +
                " (runtimeAudioFormat=" + runtimeAudioFormat + ")."
            );
        }

        onLoaded(clip);
    }
}